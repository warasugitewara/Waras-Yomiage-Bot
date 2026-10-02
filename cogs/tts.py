"""TTS Cog — 読み上げ機能の全コマンドとイベントハンドラ"""

import asyncio
import collections
import io
import wave
import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from channel_store import ChannelStore, WordDict
from discord_helpers import send_response
from guild_settings import GuildSettingsStore
from text_filter import filter_message
from voicevox import VoicevoxClient, VoicevoxError

if TYPE_CHECKING:
    from bot import YomiageBot

# Discord メッセージの安全な最大文字数
_DISCORD_MAX = 1900

# PCM キャッシュの上限（48kHz stereo s16le は 1秒あたり約 192KB）
_PCM_CACHE_MAX = 100
_PCM_CACHE_MAX_BYTES = 64 * 1024 * 1024

# VOICEVOX への同時合成リクエスト数（ギルド数が増えてもエンジン VM を過負荷にしない）
_SYNTH_CONCURRENCY = 2

# 読み替え辞書の上限（巨大入力による負荷・メモリ消費を防ぐ）
_DICT_IMPORT_MAX_BYTES = 1024 * 1024
_DICT_MAX_ENTRIES = 5000
_DICT_WORD_MAX_LEN = 50
_DICT_READING_MAX_LEN = 100

# 名前読み上げ時の名前の最大文字数（長い表示名で本文が埋もれないように）
_NAME_MAX_LEN = 20


def _validate_dict_entry(word: str, reading: str) -> str | None:
    """辞書エントリを検証し、不正ならエラーメッセージを返す"""
    if not word.strip():
        return "⚠️ 空の単語は登録できません。"
    if len(word) > _DICT_WORD_MAX_LEN:
        return f"⚠️ 単語は {_DICT_WORD_MAX_LEN} 文字以内で指定してください。"
    if len(reading) > _DICT_READING_MAX_LEN:
        return f"⚠️ 読みは {_DICT_READING_MAX_LEN} 文字以内で指定してください。"
    return None


def _extract_discord_pcm(wav_bytes: bytes) -> bytes | None:
    """WAV が既に Discord 形式（48kHz stereo s16le 非圧縮）ならヘッダを除いた PCM を返す。
    形式が異なる・解析できない・空の場合は None（FFmpeg 変換へフォールバック）。
    """
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            if (w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getcomptype()) != (48000, 2, 2, "NONE"):
                return None
            pcm = w.readframes(w.getnframes())
    except (wave.Error, EOFError):
        return None
    return pcm or None


def _require_guild(ctx_or_inter: commands.Context | discord.Interaction) -> discord.Guild:
    """ギルド必須コマンド用。DM は cog_check / interaction_check で弾かれるため通常は到達しない"""
    guild = ctx_or_inter.guild
    if guild is None:
        raise commands.NoPrivateMessage()
    return guild


def _voice_client(guild: discord.Guild) -> discord.VoiceClient | None:
    """guild.voice_client は VoiceProtocol 型のため VoiceClient に絞り込んで返す"""
    vc = guild.voice_client
    return vc if isinstance(vc, discord.VoiceClient) else None


def _listen_permission_error(
    guild: discord.Guild,
    channel_id: int,
    user: discord.abc.User,
) -> str | None:
    """読み上げ対象に追加してよいか確認し、不可ならエラーメッセージを返す。

    チャンネル ID を直接指定すると、実行者に見えない非公開チャンネルも指定できてしまうため、
    実行者と、Bot が接続中の VC にいる全員がそのチャンネルを閲覧できることを確認する。
    """
    channel = guild.get_channel(channel_id)
    member = guild.get_member(user.id)
    if channel is None or member is None or not channel.permissions_for(member).view_channel:
        return "⚠️ あなたが閲覧できないチャンネルは読み上げ対象にできません。"
    vc = _voice_client(guild)
    if vc is not None:
        for m in vc.channel.members:
            if not m.bot and not channel.permissions_for(m).view_channel:
                return "⚠️ VC 内にこのチャンネルを閲覧できないメンバーがいるため、読み上げ対象にできません。"
    return None


async def _wav_to_pcm(wav_bytes: bytes) -> bytes:
    """VOICEVOX出力WAVをDiscord用PCM(48kHz stereo s16le)に変換する。
    VOICEVOX に 48kHz stereo を指定しているため通常はヘッダ除去のみで済む。
    それ以外の形式（旧エンジン等）の場合のみ FFmpeg で変換する。
    変換はsynthesizerタスク内で1回だけ実行し、結果をキャッシュする。
    playerタスクはdiscord.PCMAudioで直接再生するためFFmpegプロセスを起動しない。

    ffmpeg が異常終了した場合や出力が空の場合は RuntimeError を送出する。
    これを怠ると空の PCM がキャッシュに保存され、同じテキストが以後ずっと
    無音再生になってしまう。
    """
    pcm = _extract_discord_pcm(wav_bytes)
    if pcm is not None:
        return pcm

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-i", "pipe:0",
        "-f", "s16le", "-ar", "48000", "-ac", "2",
        "-threads", "1",
        "-loglevel", "error", "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    pcm, stderr = await proc.communicate(wav_bytes)
    if proc.returncode != 0 or not pcm:
        detail = stderr.decode("utf-8", errors="replace").strip() or "出力が空です"
        raise RuntimeError(f"ffmpeg 変換に失敗しました（code={proc.returncode}）: {detail}")
    return pcm


@dataclass
class TTSItem:
    """キューに積む読み上げ1件分のデータ（enqueue時点で解決済み）"""
    text: str
    speaker_id: int
    speed: float


class TTS(commands.Cog):
    def __init__(self, bot: "YomiageBot"):
        self.bot = bot
        self.voicevox = VoicevoxClient(os.getenv("VOICEVOX_URL", "http://localhost:50021"))
        self.channel_store = ChannelStore()
        self.word_dict = WordDict()
        self.guild_settings = GuildSettingsStore()

        self.default_speaker = int(os.getenv("DEFAULT_SPEAKER", "3"))
        self.default_speed = float(os.getenv("DEFAULT_SPEED", "1.0"))
        self.max_length = int(os.getenv("MAX_TEXT_LENGTH", "100"))

        # UserVoiceStore は bot 側で管理し、Owner Cog と共有
        self.user_voice = bot.user_voice_store

        # guild_id → speed(float)
        self._speed: dict[int, float] = {}

        # guild_id → asyncio.Queue[TTSItem]  (メッセージキュー)
        self._queues: dict[int, asyncio.Queue] = {}

        # guild_id → asyncio.Queue[io.BytesIO]  (再生待ちPCMキュー、最大2件先読み)
        self._pcm_queues: dict[int, asyncio.Queue] = {}

        # guild_id → (synthesizer_task, player_task)
        self._workers: dict[int, tuple[asyncio.Task | None, asyncio.Task | None]] = {}

        # guild_id → auto-leave task（誰もいなくなったら5秒後に退出）
        self._auto_leave_tasks: dict[int, asyncio.Task] = {}

        # guild_id → 自動参加の排他ロック（同時入室で二重接続しないため）
        self._autojoin_locks: dict[int, asyncio.Lock] = {}

        # guild_id → 直前に読み上げたメッセージの発言者ID（連続投稿時は名前を省略する）
        self._last_author: dict[int, int] = {}

        # スピーカー一覧キャッシュ（初回fetch後に永続。reload_speakersでリセット）
        self._speakers_cache: list[dict] | None = None
        self._speaker_id_map: dict[int, tuple[str, str]] | None = None  # id → (char, style)
        self._speakers_lock = asyncio.Lock()

        # PCM LRU キャッシュ (text, speaker_id, speed) → 48kHz stereo s16le bytes
        # キャッシュヒット時はFFmpeg変換・VOICEVOX合成いずれも省略
        self._pcm_cache: collections.OrderedDict[tuple, bytes] = collections.OrderedDict()
        self._pcm_cache_bytes = 0

        # in-flight dedup: 合成中キーを共有 Task で管理（ギルド横断共有）
        # 同じ (text, speaker_id, speed) が既に合成中なら Task を shield して待つ。
        # Task はどのギルドのワーカーにも所有されないため、/leave でワーカーが
        # キャンセルされても合成は継続し、他ギルドの待機が停止しない
        self._in_flight: dict[tuple, asyncio.Task[bytes]] = {}
        self._synth_sem = asyncio.Semaphore(_SYNTH_CONCURRENCY)

        # ウォームアップ Task の参照（GC による途中消失を防ぎ、unload 時にキャンセルする）
        self._warmup_task: asyncio.Task[None] | None = None

    async def cog_check(self, ctx: commands.Context) -> bool:
        """読み上げ系コマンドはサーバー内でのみ使用可能（DM では無視される）"""
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        return True

    async def interaction_check(self, interaction: discord.Interaction, /) -> bool:
        if interaction.guild is None:
            raise app_commands.NoPrivateMessage()
        return True

    async def cog_load(self):
        """Cog 読み込み完了後にウォームアップタスクを起動する"""
        self._warmup_task = asyncio.create_task(self._warmup(), name="voicevox-warmup")

    async def cog_unload(self):
        """シャットダウン: タスクキャンセル → gather → in_flight クリア → セッションクローズ"""
        # 1. 全タスクをキャンセル
        tasks: list[asyncio.Task] = []
        for synth, play in self._workers.values():
            if synth and not synth.done():
                synth.cancel()
                tasks.append(synth)
            if play and not play.done():
                play.cancel()
                tasks.append(play)
        for task in self._auto_leave_tasks.values():
            if not task.done():
                task.cancel()
                tasks.append(task)
        if self._warmup_task and not self._warmup_task.done():
            self._warmup_task.cancel()
            tasks.append(self._warmup_task)

        # 2. 共有合成 Task をキャンセル（完了時コールバックで _in_flight から外れる）
        for task in self._in_flight.values():
            if not task.done():
                task.cancel()
                tasks.append(task)

        # 3. キャンセルが処理されるまで待機（finally ブロックの実行を保証）
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # 4. VoicevoxClient セッションをクローズ（タスク終了後）
        await self.voicevox.close()

    async def _warmup(self):
        """起動後に短文を事前合成してキャッシュ & VOICEVOXエンジンのモデルをウォームアップする"""
        await asyncio.sleep(3)  # Bot接続が安定するまで待機
        key = ("接続しました", self.default_speaker, self.default_speed)
        if key in self._pcm_cache:
            return
        try:
            wav = await self.voicevox.synthesis("接続しました", self.default_speaker, self.default_speed)
            pcm = await _wav_to_pcm(wav)
            self._cache_put(key, pcm)
            print("[TTS] VOICEVOXウォームアップ完了（「接続しました」をキャッシュ）")
        except Exception as e:
            print(f"[TTS] VOICEVOXウォームアップ失敗（起動直後は正常）: {e}")

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _guild_speed(self, guild_id: int) -> float:
        return self._speed.get(guild_id, self.default_speed)

    def _get_queue(self, guild_id: int) -> asyncio.Queue:
        if guild_id not in self._queues:
            self._queues[guild_id] = asyncio.Queue(maxsize=50)
        return self._queues[guild_id]

    def _get_pcm_queue(self, guild_id: int) -> asyncio.Queue:
        if guild_id not in self._pcm_queues:
            # 最大2件先読みして再生待ちPCMをバッファリング
            self._pcm_queues[guild_id] = asyncio.Queue(maxsize=2)
        return self._pcm_queues[guild_id]

    def _ensure_worker(self, guild_id: int):
        synth, play = self._workers.get(guild_id, (None, None))
        if synth is None or synth.done():
            synth = asyncio.create_task(
                self._synthesizer(guild_id), name=f"synth-{guild_id}"
            )
        if play is None or play.done():
            play = asyncio.create_task(
                self._player(guild_id), name=f"player-{guild_id}"
            )
        self._workers[guild_id] = (synth, play)

    def _cancel_workers(self, guild_id: int):
        """合成タスクと再生タスクをキャンセルしてキューを空にする"""
        synth, play = self._workers.pop(guild_id, (None, None))
        if synth:
            synth.cancel()
        if play:
            play.cancel()
        for q in (self._queues.pop(guild_id, None), self._pcm_queues.pop(guild_id, None)):
            if q:
                while not q.empty():
                    try:
                        q.get_nowait()
                        q.task_done()
                    except Exception:
                        pass

    def _cancel_auto_leave(self, guild_id: int):
        """スケジュール済みの自動退出タスクをキャンセルする"""
        task = self._auto_leave_tasks.pop(guild_id, None)
        if task and not task.done():
            task.cancel()

    def _schedule_auto_leave(self, guild_id: int):
        """誰もいなくなったら5秒後に自動退出タスクをスケジュールする"""
        self._cancel_auto_leave(guild_id)
        self._auto_leave_tasks[guild_id] = asyncio.create_task(
            self._auto_leave(guild_id), name=f"auto-leave-{guild_id}"
        )

    async def _auto_leave(self, guild_id: int):
        """5秒待ってもVC内に人間がいなければ自動退出する"""
        await asyncio.sleep(5)
        self._auto_leave_tasks.pop(guild_id, None)
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return
        vc = _voice_client(guild)
        if vc is None:
            return
        non_bots = [m for m in vc.channel.members if not m.bot]
        if non_bots:
            return
        self.channel_store.clear(guild_id)
        self._speed.pop(guild_id, None)
        self._last_author.pop(guild_id, None)
        self._cancel_workers(guild_id)
        try:
            await vc.disconnect()
        except Exception as e:
            print(f"[AUTO-LEAVE ERROR] {e}")
            await self.bot.webhook.send(
                "warning", "自動退出エラー", exc=e,
                context={"guild_id": str(guild_id)},
            )

    def _get_or_start_synthesis(self, cache_key: tuple, item: TTSItem) -> asyncio.Task[bytes]:
        """cache_key の共有合成 Task を返す。未開始なら開始する"""
        task = self._in_flight.get(cache_key)
        if task is None:
            task = asyncio.create_task(
                self._synthesize_pcm(cache_key, item), name="tts-shared-synthesis"
            )
            self._in_flight[cache_key] = task
            task.add_done_callback(
                lambda t, key=cache_key: self._on_synthesis_done(key, t)
            )
        return task

    def _on_synthesis_done(self, cache_key: tuple, task: asyncio.Task[bytes]) -> None:
        if self._in_flight.get(cache_key) is task:
            del self._in_flight[cache_key]
        # 待機ワーカーが全員キャンセル済みでも "exception was never retrieved" を出さない
        if not task.cancelled():
            task.exception()

    async def _synthesize_pcm(self, cache_key: tuple, item: TTSItem) -> bytes:
        """VOICEVOX 合成 → PCM 変換し、キャッシュへ保存して返す"""
        async with self._synth_sem:
            wav_bytes = await self.voicevox.synthesis(item.text, item.speaker_id, item.speed)
        pcm_bytes = await _wav_to_pcm(wav_bytes)
        # キャッシュ更新（VC切断に関わらず次回のために保存）
        self._cache_put(cache_key, pcm_bytes)
        return pcm_bytes

    def _cache_put(self, key: tuple, pcm: bytes) -> None:
        """PCM を LRU キャッシュに保存し、件数・合計バイト数の上限まで古い順に破棄する"""
        old = self._pcm_cache.pop(key, None)
        if old is not None:
            self._pcm_cache_bytes -= len(old)
        if len(pcm) > _PCM_CACHE_MAX_BYTES:
            return  # 単体で上限を超える音声はキャッシュしない
        self._pcm_cache[key] = pcm
        self._pcm_cache_bytes += len(pcm)
        while (
            len(self._pcm_cache) > _PCM_CACHE_MAX
            or self._pcm_cache_bytes > _PCM_CACHE_MAX_BYTES
        ):
            _, evicted = self._pcm_cache.popitem(last=False)
            self._pcm_cache_bytes -= len(evicted)

    async def _synthesizer(self, guild_id: int):
        """メッセージキューからTTSItemを取り出し、PCMに変換してPCMキューに積む"""
        msg_q = self._get_queue(guild_id)
        pcm_q = self._get_pcm_queue(guild_id)
        while True:
            item: TTSItem = await msg_q.get()
            try:
                guild = self.bot.get_guild(guild_id)
                if guild is None or guild.voice_client is None:
                    continue

                cache_key = (item.text, item.speaker_id, item.speed)

                # キャッシュヒット確認（awaitを挟まないので安全）
                if cache_key in self._pcm_cache:
                    self._pcm_cache.move_to_end(cache_key)
                    pcm_bytes = self._pcm_cache[cache_key]
                else:
                    # 新規合成、または別ギルドが合成中の共有 Task を待つ。
                    # shield によりこのワーカーのキャンセルは Task へ伝播しない
                    task = self._get_or_start_synthesis(cache_key, item)
                    pcm_bytes = await asyncio.shield(task)

                    # 合成後にVC接続を確認（合成中に切断された場合は再生をスキップ）
                    if guild.voice_client is None:
                        continue

                await pcm_q.put(pcm_bytes)
            except VoicevoxError as e:
                print(f"[VOICEVOX ERROR] {e}")
                await self.bot.webhook.send(
                    "warning", "VOICEVOX 合成エラー", str(e),
                    context={"guild_id": str(guild_id)},
                )
            except Exception as e:
                print(f"[SYNTH ERROR] {e}")
                await self.bot.webhook.send(
                    "error", "合成タスク エラー", exc=e,
                    context={"guild_id": str(guild_id)},
                )
            finally:
                msg_q.task_done()

    async def _player(self, guild_id: int):
        """PCMキューから音声を取り出してVCで直接再生する（FFmpegプロセス不要）"""
        pcm_q = self._get_pcm_queue(guild_id)
        loop = asyncio.get_running_loop()
        while True:
            pcm: bytes = await pcm_q.get()
            try:
                guild = self.bot.get_guild(guild_id)
                vc = _voice_client(guild) if guild else None
                if vc and vc.is_connected():
                    event = asyncio.Event()
                    play_error: list[Exception | None] = [None]

                    def _after(err, *, _ev=event, _eh=play_error):
                        _eh[0] = err
                        loop.call_soon_threadsafe(_ev.set)

                    # discord.PCMAudio はチャンネルのビットレート（128kbps等）を
                    # discord.py のOpusエンコーダが自動参照するため指定不要
                    source = discord.PCMAudio(io.BytesIO(pcm))
                    vc.play(source, after=_after)
                    await event.wait()
                    if play_error[0]:
                        raise play_error[0]
            except Exception as e:
                print(f"[PLAYER ERROR] {e}")
                await self.bot.webhook.send(
                    "warning", "再生エラー", exc=e,
                    context={"guild_id": str(guild_id)},
                )
            finally:
                pcm_q.task_done()

    async def _join_vc(self, voice_channel: discord.VoiceChannel | discord.StageChannel):
        """VCに参加してワーカーを起動する共通処理"""
        guild_id = voice_channel.guild.id
        vc = _voice_client(voice_channel.guild)

        if vc is not None:
            if vc.channel == voice_channel:
                return vc, False
            await vc.move_to(voice_channel)
        else:
            vc = await voice_channel.connect(self_deaf=True)

        self._ensure_worker(guild_id)
        return vc, True

    def _enqueue_announce(self, guild_id: int, text: str):
        """システムアナウンスをデフォルトスピーカーでキューに積む（満杯なら最古を捨てる）"""
        item = TTSItem(
            text=text,
            speaker_id=self.default_speaker,
            speed=self._guild_speed(guild_id),
        )
        self._enqueue_item(guild_id, item)

    def _enqueue_item(self, guild_id: int, item: TTSItem):
        """メッセージキューに積む（満杯なら最古を捨てる）"""
        q = self._get_queue(guild_id)
        if q.full():
            try:
                q.get_nowait()
                # 捨てた要素も処理済みとして数え、未完了カウンタのずれを防ぐ
                q.task_done()
            except asyncio.QueueEmpty:
                pass
        q.put_nowait(item)
        self._ensure_worker(guild_id)

    async def _ensure_speakers_cache(self) -> bool:
        """スピーカーキャッシュを初回のみフェッチする。成功で True、失敗で False"""
        if self._speakers_cache is not None:
            return True
        async with self._speakers_lock:
            if self._speakers_cache is not None:
                return True
            try:
                speakers = await self.voicevox.get_speakers()
                self._speakers_cache = speakers
                self._speaker_id_map = {
                    style["id"]: (sp["name"], style["name"])
                    for sp in speakers
                    for style in sp["styles"]
                }
                return True
            except VoicevoxError:
                return False

    async def _get_valid_speaker_ids(self) -> set[int] | None:
        """有効な speaker_id セットを返す（キャッシュ利用）。失敗時は None"""
        if not await self._ensure_speakers_cache() or self._speaker_id_map is None:
            return None
        return set(self._speaker_id_map.keys())

    async def _resolve_speaker_name(self, speaker_id: int) -> str | None:
        """speaker_id から「キャラ名 / スタイル名」の文字列を返す（キャッシュ利用）"""
        if not await self._ensure_speakers_cache() or self._speaker_id_map is None:
            return None
        entry = self._speaker_id_map.get(speaker_id)
        return f"{entry[0]} / {entry[1]}" if entry else None

    async def _resolve_credit(self, speaker_id: int) -> str | None:
        """speaker_id から VOICEVOX のクレジット表記（例: VOICEVOX:ずんだもん）を返す"""
        if not await self._ensure_speakers_cache() or self._speaker_id_map is None:
            return None
        entry = self._speaker_id_map.get(speaker_id)
        return f"VOICEVOX:{entry[0]}" if entry else None

    async def _send(self, ctx_or_inter, msg: str, ephemeral: bool = False):
        await send_response(ctx_or_inter, msg, ephemeral=ephemeral)

    async def _send_chunks(self, ctx_or_inter, text: str, ephemeral: bool = False):
        """長いテキストを _DISCORD_MAX 文字以内に分割して送信"""
        chunks = [text[i:i + _DISCORD_MAX] for i in range(0, len(text), _DISCORD_MAX)]
        for i, chunk in enumerate(chunks):
            if i == 0:
                await self._send(ctx_or_inter, chunk, ephemeral=ephemeral)
            else:
                if isinstance(ctx_or_inter, discord.Interaction):
                    await ctx_or_inter.followup.send(chunk, ephemeral=ephemeral)
                else:
                    await ctx_or_inter.send(chunk)

    # ------------------------------------------------------------------ #
    # Basic commands
    # ------------------------------------------------------------------ #

    @commands.hybrid_command(name="join", description="VCに参加して読み上げを開始します")
    async def join(self, ctx: commands.Context):
        guild = _require_guild(ctx)
        author = ctx.author
        voice_channel = (
            author.voice.channel
            if isinstance(author, discord.Member) and author.voice
            else None
        )
        if voice_channel is None:
            await ctx.send("先にボイスチャンネルに参加してください。", ephemeral=True)
            return

        # VC接続は3秒を超える場合があるため事前に defer
        await ctx.defer()
        try:
            vc, joined = await self._join_vc(voice_channel)
        except discord.ClientException as e:
            await ctx.send(f"⚠️ VC への接続に失敗しました: {e}")
            return
        except Exception as e:
            await ctx.send(f"⚠️ 予期しないエラーが発生しました: {e}")
            return

        self.channel_store.add(guild.id, ctx.channel.id)

        if joined:
            self._enqueue_announce(guild.id, "接続しました")

        # slash コマンドは defer 後に必ず応答が必要（ユーザーのみ見える）
        if ctx.interaction:
            await ctx.send("✅", ephemeral=True)

    @commands.hybrid_command(name="leave", aliases=["quit", "stop", "bye", "exit"], description="VCから退出して読み上げを停止します")
    async def leave(self, ctx: commands.Context):
        guild = _require_guild(ctx)
        vc = _voice_client(guild)
        if vc is None:
            await ctx.send("ボイスチャンネルに接続していません。", ephemeral=True)
            return

        await ctx.defer()
        guild_id = guild.id
        self._cancel_auto_leave(guild_id)
        self.channel_store.clear(guild_id)
        self._speed.pop(guild_id, None)
        self._last_author.pop(guild_id, None)
        self._cancel_workers(guild_id)

        try:
            await vc.disconnect()
        except Exception as e:
            await ctx.send(f"⚠️ 退出時にエラーが発生しました: {e}")
            return
        await ctx.send("👋 退出しました。")

    @commands.hybrid_command(name="skip", description="現在の読み上げをスキップします")
    async def skip(self, ctx: commands.Context):
        vc = _voice_client(_require_guild(ctx))
        if vc is None or not vc.is_playing():
            await ctx.send("現在再生中の音声はありません。", ephemeral=True)
            return
        vc.stop()
        await ctx.send("⏭️ スキップしました。")

    @commands.hybrid_command(name="speed", description="サーバー全体の読み上げ速度を変更します（0.5〜2.0、サーバー管理権限が必要）")
    @app_commands.describe(value="速度倍率（0.5〜2.0）")
    @app_commands.default_permissions(manage_guild=True)
    @commands.has_permissions(manage_guild=True)
    async def speed(self, ctx: commands.Context, value: float):
        if not 0.5 <= value <= 2.0:
            await ctx.send("速度は 0.5〜2.0 の範囲で指定してください。", ephemeral=True)
            return
        self._speed[_require_guild(ctx).id] = value
        await ctx.send(f"⚡ 速度を `{value}` に変更しました。")

    # ------------------------------------------------------------------ #
    # myvoice コマンドグループ（ユーザー個別ボイス設定）
    # ------------------------------------------------------------------ #

    @commands.group(name="myvoice", invoke_without_command=True)
    async def myvoice_group(self, ctx: commands.Context):
        await ctx.send_help(ctx.command)

    myvoice_app = app_commands.Group(name="myvoice", description="自分の読み上げボイス設定")

    # --- set ---

    @myvoice_group.command(name="set")
    async def myvoice_set_prefix(self, ctx: commands.Context, speaker_id: int):
        await ctx.defer()
        await self._myvoice_set(ctx, speaker_id)

    @myvoice_app.command(name="set", description="自分の読み上げボイスを設定します")
    @app_commands.describe(speaker_id="VOICEVOX のスピーカーID（/myvoice list で確認）")
    async def myvoice_set_slash(self, inter: discord.Interaction, speaker_id: int):
        await inter.response.defer(ephemeral=False)
        await self._myvoice_set(inter, speaker_id)

    async def _myvoice_set(self, ctx_or_inter, speaker_id: int):
        valid_ids = await self._get_valid_speaker_ids()
        if valid_ids is not None and speaker_id not in valid_ids:
            await self._send(
                ctx_or_inter,
                f"⚠️ ID `{speaker_id}` は存在しません。`/myvoice list` で有効なIDを確認してください。",
                ephemeral=True,
            )
            return
        user_id = (
            ctx_or_inter.author.id
            if isinstance(ctx_or_inter, commands.Context)
            else ctx_or_inter.user.id
        )
        self.user_voice.set(user_id, speaker_id)
        msg = f"🎤 あなたのボイスを ID `{speaker_id}` に設定しました。"
        credit = await self._resolve_credit(speaker_id)
        if credit:
            msg += f"\n📜 クレジット: `{credit}`（キャラクターの利用規約に従ってご利用ください）"
        await self._send(ctx_or_inter, msg)

    # --- reset ---

    @myvoice_group.command(name="reset")
    async def myvoice_reset_prefix(self, ctx: commands.Context):
        await ctx.defer()
        await self._myvoice_reset(ctx)

    @myvoice_app.command(name="reset", description="自分のボイス設定をデフォルト（ずんだもん ノーマル）に戻します")
    async def myvoice_reset_slash(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=False)
        await self._myvoice_reset(inter)

    async def _myvoice_reset(self, ctx_or_inter):
        user_id = (
            ctx_or_inter.author.id
            if isinstance(ctx_or_inter, commands.Context)
            else ctx_or_inter.user.id
        )
        self.user_voice.reset(user_id)
        await self._send(ctx_or_inter, f"🔄 ボイスをデフォルト（ID `{self.default_speaker}`）にリセットしました。")

    # --- info ---

    @myvoice_group.command(name="info")
    async def myvoice_info_prefix(self, ctx: commands.Context):
        await ctx.defer()
        await self._myvoice_info(ctx)

    @myvoice_app.command(name="info", description="現在の自分のボイス設定を表示します")
    async def myvoice_info_slash(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        await self._myvoice_info(inter)

    async def _myvoice_info(self, ctx_or_inter):
        user_id = (
            ctx_or_inter.author.id
            if isinstance(ctx_or_inter, commands.Context)
            else ctx_or_inter.user.id
        )
        speaker_id = self.user_voice.get(user_id)
        name = await self._resolve_speaker_name(speaker_id)
        label = f"`{name}`" if name else f"ID `{speaker_id}`"
        msg = f"🎤 現在のボイス: {label} (ID: `{speaker_id}`)"
        credit = await self._resolve_credit(speaker_id)
        if credit:
            msg += f"\n📜 クレジット: `{credit}`"
        await self._send(ctx_or_inter, msg, ephemeral=True)

    # --- list ---

    @myvoice_group.command(name="list")
    async def myvoice_list_prefix(self, ctx: commands.Context):
        await ctx.defer()
        await self._myvoice_list(ctx)

    @myvoice_app.command(name="list", description="利用可能なスピーカー一覧を表示します")
    async def myvoice_list_slash(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        await self._myvoice_list(inter)

    async def _myvoice_list(self, ctx_or_inter):
        if not await self._ensure_speakers_cache():
            await self._send(ctx_or_inter, "⚠️ VOICEVOX に接続できません。", ephemeral=True)
            return

        lines = ["🎤 **利用可能なスピーカー一覧**\n"]
        for sp in self._speakers_cache or []:
            styles = " | ".join(f"{s['name']}: `{s['id']}`" for s in sp["styles"])
            lines.append(f"**{sp['name']}**\n　{styles}")

        await self._send_chunks(ctx_or_inter, "\n".join(lines), ephemeral=True)

    # /voice を /myvoice set のエイリアスとして残す
    @commands.hybrid_command(name="voice", description="自分の読み上げボイスを設定します（/myvoice set と同じ）")
    @app_commands.describe(speaker_id="VOICEVOX のスピーカーID（/myvoice list で確認）")
    async def voice(self, ctx: commands.Context, speaker_id: int):
        await ctx.defer()
        await self._myvoice_set(ctx, speaker_id)

    # ------------------------------------------------------------------ #
    # listen サブコマンドグループ
    # ------------------------------------------------------------------ #

    @commands.group(name="listen", invoke_without_command=True)
    async def listen_group(self, ctx: commands.Context):
        await ctx.send_help(ctx.command)

    listen_app = app_commands.Group(name="listen", description="読み上げチャンネルの管理")

    @listen_group.command(name="add")
    async def listen_add_prefix(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        await self._listen_add(ctx, channel or ctx.channel)

    @listen_app.command(name="add", description="読み上げ対象チャンネルを追加します")
    @app_commands.describe(channel="追加するテキストチャンネル（省略時は現在のチャンネル）")
    async def listen_add_slash(self, inter: discord.Interaction, channel: discord.TextChannel | None = None):
        await self._listen_add(inter, channel or inter.channel)

    async def _listen_add(self, ctx_or_inter, channel: discord.abc.Snowflake | None):
        if channel is None:
            await self._send(ctx_or_inter, "⚠️ チャンネルを特定できませんでした。", ephemeral=True)
            return
        guild = _require_guild(ctx_or_inter)
        user = ctx_or_inter.user if isinstance(ctx_or_inter, discord.Interaction) else ctx_or_inter.author
        error = _listen_permission_error(guild, channel.id, user)
        if error:
            await self._send(ctx_or_inter, error, ephemeral=True)
            return
        added = self.channel_store.add(guild.id, channel.id)
        msg = f"📢 <#{channel.id}> を読み上げ対象に追加しました。" if added else f"<#{channel.id}> はすでに登録済みです。"
        await self._send(ctx_or_inter, msg)

    @listen_group.command(name="remove")
    async def listen_remove_prefix(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        await self._listen_remove(ctx, channel or ctx.channel)

    @listen_app.command(name="remove", description="読み上げ対象チャンネルを削除します")
    @app_commands.describe(channel="削除するテキストチャンネル（省略時は現在のチャンネル）")
    async def listen_remove_slash(self, inter: discord.Interaction, channel: discord.TextChannel | None = None):
        await self._listen_remove(inter, channel or inter.channel)

    async def _listen_remove(self, ctx_or_inter, channel: discord.abc.Snowflake | None):
        if channel is None:
            await self._send(ctx_or_inter, "⚠️ チャンネルを特定できませんでした。", ephemeral=True)
            return
        guild = ctx_or_inter.guild
        removed = self.channel_store.remove(guild.id, channel.id)
        msg = f"🔇 <#{channel.id}> を読み上げ対象から削除しました。" if removed else f"<#{channel.id}> は登録されていません。"
        await self._send(ctx_or_inter, msg)

    @listen_group.command(name="list")
    async def listen_list_prefix(self, ctx: commands.Context):
        await self._listen_list(ctx)

    @listen_app.command(name="list", description="読み上げ対象チャンネル一覧を表示します")
    async def listen_list_slash(self, inter: discord.Interaction):
        await self._listen_list(inter)

    async def _listen_list(self, ctx_or_inter):
        channels = self.channel_store.get(ctx_or_inter.guild.id)
        if not channels:
            msg = "読み上げ対象のチャンネルが登録されていません。"
        else:
            lines = "\n".join(f"• <#{cid}>" for cid in channels)
            msg = f"📋 読み上げ対象チャンネル:\n{lines}"
        await self._send(ctx_or_inter, msg)

    # ------------------------------------------------------------------ #
    # dict サブコマンドグループ
    # ------------------------------------------------------------------ #

    @commands.group(name="dict", invoke_without_command=True)
    async def dict_group(self, ctx: commands.Context):
        await ctx.send_help(ctx.command)

    dict_app = app_commands.Group(name="dict", description="読み替え辞書の管理")

    @dict_group.command(name="add")
    async def dict_add_prefix(self, ctx: commands.Context, word: str, reading: str):
        await self._dict_add(ctx, word, reading)

    @dict_app.command(name="add", description="読み替え辞書に単語を追加します")
    @app_commands.describe(word="元の単語", reading="読み替え後のテキスト")
    async def dict_add_slash(self, inter: discord.Interaction, word: str, reading: str):
        await self._dict_add(inter, word, reading)

    async def _dict_add(self, ctx_or_inter, word: str, reading: str):
        guild_id = ctx_or_inter.guild.id
        error = _validate_dict_entry(word, reading)
        current = self.word_dict.all(guild_id)
        if error is None and word not in current and len(current) >= _DICT_MAX_ENTRIES:
            error = f"⚠️ 辞書の登録数が上限（{_DICT_MAX_ENTRIES}件）に達しています。"
        if error:
            await self._send(ctx_or_inter, error, ephemeral=True)
            return
        self.word_dict.add(guild_id, word, reading)
        await self._send(ctx_or_inter, f"📖 `{word}` → `{reading}` を辞書に追加しました。")

    @dict_group.command(name="remove")
    async def dict_remove_prefix(self, ctx: commands.Context, word: str):
        removed = self.word_dict.remove(_require_guild(ctx).id, word)
        await ctx.send(f"🗑️ `{word}` を削除しました。" if removed else f"`{word}` は辞書にありません。")

    @dict_app.command(name="remove", description="読み替え辞書から単語を削除します")
    @app_commands.describe(word="削除する単語")
    async def dict_remove_slash(self, inter: discord.Interaction, word: str):
        removed = self.word_dict.remove(_require_guild(inter).id, word)
        await inter.response.send_message(
            f"🗑️ `{word}` を削除しました。" if removed else f"`{word}` は辞書にありません。"
        )

    @dict_group.command(name="list")
    async def dict_list_prefix(self, ctx: commands.Context):
        await self._dict_list(ctx)

    @dict_app.command(name="list", description="読み替え辞書の一覧を表示します")
    async def dict_list_slash(self, inter: discord.Interaction):
        await self._dict_list(inter)

    async def _dict_list(self, ctx_or_inter):
        guild_id = ctx_or_inter.guild.id
        d = self.word_dict.all(guild_id)
        if not d:
            msg = "辞書は空です。"
        else:
            lines = "\n".join(f"• `{w}` → `{r}`" for w, r in d.items())
            msg = f"📖 読み替え辞書 ({len(d)}件):\n{lines}"
        await self._send_chunks(ctx_or_inter, msg)

    @dict_group.command(name="export")
    async def dict_export_prefix(self, ctx: commands.Context):
        await self._dict_export(ctx)

    @dict_app.command(name="export", description="辞書をJSONファイルとしてエクスポートします")
    async def dict_export_slash(self, inter: discord.Interaction):
        await self._dict_export(inter)

    async def _dict_export(self, ctx_or_inter):
        guild_id = ctx_or_inter.guild.id
        d = self.word_dict.export_dict(guild_id)
        payload = {
            "version": 1,
            "data": [{"word": w, "reading": r} for w, r in d.items()],
        }
        buf = io.BytesIO(json.dumps(payload, ensure_ascii=False, indent=2).encode())
        buf.seek(0)
        file = discord.File(buf, filename=f"dict_{guild_id}.json")
        if isinstance(ctx_or_inter, discord.Interaction):
            await ctx_or_inter.response.send_message(
                f"📤 辞書をエクスポートしました（{len(d)}件）", file=file
            )
        else:
            await ctx_or_inter.send(f"📤 辞書をエクスポートしました（{len(d)}件）", file=file)

    @dict_group.command(name="import")
    @commands.has_permissions(manage_guild=True)
    async def dict_import_prefix(self, ctx: commands.Context, replace: bool = False):
        if not ctx.message.attachments:
            await ctx.send("⚠️ JSONファイルを添付してください。")
            return
        await ctx.defer()
        await self._dict_import(ctx, ctx.message.attachments[0], replace)

    @dict_app.command(name="import", description="JSONファイルから辞書をインポートします（サーバー管理権限が必要）")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        file="インポートするJSONファイル",
        replace="True で既存辞書を全置換（デフォルト: False でマージ）",
    )
    async def dict_import_slash(
        self,
        inter: discord.Interaction,
        file: discord.Attachment,
        replace: bool = False,
    ):
        await inter.response.defer()
        await self._dict_import(inter, file, replace)

    async def _dict_import(self, ctx_or_inter, attachment: discord.Attachment, replace: bool):
        if not attachment.filename.endswith(".json"):
            await self._send(ctx_or_inter, "⚠️ `.json` ファイルのみ対応しています。")
            return
        # 読み込み前にサイズを検査（巨大ファイルをメモリへ展開しない）
        if attachment.size > _DICT_IMPORT_MAX_BYTES:
            await self._send(
                ctx_or_inter,
                f"⚠️ ファイルサイズが上限（{_DICT_IMPORT_MAX_BYTES // 1024}KB）を超えています。",
            )
            return
        try:
            raw_bytes = await attachment.read()
            data = json.loads(raw_bytes.decode("utf-8"))
        except Exception:
            await self._send(ctx_or_inter, "⚠️ JSONの読み込みに失敗しました。ファイルが正しいか確認してください。")
            return

        entries = self._parse_dict_json(data)
        if entries is None:
            await self._send(ctx_or_inter, "⚠️ サポートされていないJSONフォーマットです。")
            return

        # 空単語は読み上げに影響しないため黙ってスキップする
        entries = {w: r for w, r in entries.items() if w.strip()}
        guild_id = ctx_or_inter.guild.id
        error = self._check_dict_import(
            entries, {} if replace else self.word_dict.all(guild_id)
        )
        if error:
            await self._send(ctx_or_inter, f"{error}\nインポートは行われませんでした。")
            return

        count = self.word_dict.import_dict(guild_id, entries, replace=replace)
        mode = "全置換" if replace else "マージ"
        await self._send(ctx_or_inter, f"📥 辞書を{mode}でインポートしました（{count}件）。")

    @staticmethod
    def _check_dict_import(entries: dict[str, str], current: dict[str, str]) -> str | None:
        """インポート内容を検証する。1件でも不正なら全体を拒否するためエラーを返す"""
        for word, reading in entries.items():
            error = _validate_dict_entry(word, reading)
            if error:
                return f"{error}（`{word[:_DICT_WORD_MAX_LEN]}`）"
        total = len(current.keys() | entries.keys())
        if total > _DICT_MAX_ENTRIES:
            return f"⚠️ 登録数が上限（{_DICT_MAX_ENTRIES}件）を超えます（インポート後 {total}件）。"
        return None

    @staticmethod
    def _parse_dict_json(data: dict) -> dict[str, str] | None:
        """各種フォーマットのJSONを {word: reading} 形式に変換する。

        対応フォーマット:
        - 本Bot形式: {"version":1, "data":[{"word":"...","reading":"..."},...]}
        - kuroneko形式: {"kind":"...","version":1,"data":[{"before":"...","after":"...","regex":...},...]}
        - シンプル形式: {"word":"reading",...}
        """
        if not isinstance(data, dict):
            return None

        if "data" in data and isinstance(data["data"], list):
            result = {}
            for item in data["data"]:
                if not isinstance(item, dict):
                    continue
                if "before" in item and "after" in item:
                    # kuroneko形式
                    result[str(item["before"])] = str(item["after"])
                elif "word" in item and "reading" in item:
                    # 本Bot形式
                    result[str(item["word"])] = str(item["reading"])
            return result if result else {}

        # シンプルフラット形式 {"word": "reading"}
        if all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
            return data

        return None

    # ------------------------------------------------------------------ #
    # autojoin サブコマンドグループ（管理者向け）
    # ------------------------------------------------------------------ #

    @commands.group(name="autojoin", invoke_without_command=True)
    async def autojoin_group(self, ctx: commands.Context):
        await ctx.send_help(ctx.command)

    autojoin_app = app_commands.Group(
        name="autojoin",
        description="VC への自動参加の管理（サーバー管理権限が必要）",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @autojoin_group.command(name="add")
    @commands.has_permissions(manage_guild=True)
    async def autojoin_add_prefix(
        self,
        ctx: commands.Context,
        vc: discord.VoiceChannel,
        text: discord.TextChannel | None = None,
    ):
        await self._autojoin_add(ctx, vc, text)

    @autojoin_app.command(name="add", description="人が入ったら自動参加する VC を登録します")
    @app_commands.describe(
        vc="自動参加するボイスチャンネル",
        text="読み上げるテキストチャンネル（省略時は VC 内チャット）",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def autojoin_add_slash(
        self,
        inter: discord.Interaction,
        vc: discord.VoiceChannel,
        text: discord.TextChannel | None = None,
    ):
        await self._autojoin_add(inter, vc, text)

    async def _autojoin_add(self, ctx_or_inter, vc: discord.VoiceChannel, text: discord.TextChannel | None):
        guild = _require_guild(ctx_or_inter)
        perms = vc.permissions_for(guild.me)
        if not (perms.connect and perms.speak):
            await self._send(ctx_or_inter, f"⚠️ <#{vc.id}> に接続・発言する権限が Bot にありません。", ephemeral=True)
            return
        # テキストチャンネル未指定時は VC 内チャット（VC と同じ ID）を読み上げる
        text_id = text.id if text else vc.id
        self.guild_settings.set_autojoin(guild.id, vc.id, text_id)
        await self._send(ctx_or_inter, f"🔁 <#{vc.id}> に人が入ったら自動参加し、<#{text_id}> を読み上げます。")

    @autojoin_group.command(name="remove")
    @commands.has_permissions(manage_guild=True)
    async def autojoin_remove_prefix(self, ctx: commands.Context, vc: discord.VoiceChannel):
        await self._autojoin_remove(ctx, vc)

    @autojoin_app.command(name="remove", description="自動参加 VC の登録を解除します")
    @app_commands.describe(vc="解除するボイスチャンネル")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def autojoin_remove_slash(self, inter: discord.Interaction, vc: discord.VoiceChannel):
        await self._autojoin_remove(inter, vc)

    async def _autojoin_remove(self, ctx_or_inter, vc: discord.VoiceChannel):
        removed = self.guild_settings.remove_autojoin(_require_guild(ctx_or_inter).id, vc.id)
        msg = f"🛑 <#{vc.id}> の自動参加を解除しました。" if removed else f"<#{vc.id}> は自動参加に登録されていません。"
        await self._send(ctx_or_inter, msg)

    @autojoin_group.command(name="list")
    @commands.has_permissions(manage_guild=True)
    async def autojoin_list_prefix(self, ctx: commands.Context):
        await self._autojoin_list(ctx)

    @autojoin_app.command(name="list", description="自動参加 VC の一覧を表示します")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def autojoin_list_slash(self, inter: discord.Interaction):
        await self._autojoin_list(inter)

    async def _autojoin_list(self, ctx_or_inter):
        entries = self.guild_settings.autojoin_all(_require_guild(ctx_or_inter).id)
        if not entries:
            msg = "自動参加する VC は登録されていません。"
        else:
            lines = "\n".join(f"• <#{vc_id}> → <#{text_id}>" for vc_id, text_id in entries.items())
            msg = f"🔁 自動参加 VC（VC → 読み上げ先）:\n{lines}"
        await self._send_chunks(ctx_or_inter, msg)

    # ------------------------------------------------------------------ #
    # ignore サブコマンドグループ（読み上げ除外ユーザー）
    # ------------------------------------------------------------------ #

    @commands.group(name="ignore", invoke_without_command=True)
    async def ignore_group(self, ctx: commands.Context):
        await ctx.send_help(ctx.command)

    ignore_app = app_commands.Group(name="ignore", description="読み上げ除外ユーザーの管理")

    @ignore_group.command(name="add")
    @commands.has_permissions(manage_guild=True)
    async def ignore_add_prefix(self, ctx: commands.Context, user: discord.Member):
        await self._ignore_add(ctx, user)

    @ignore_app.command(name="add", description="ユーザーのメッセージを読み上げ対象外にします（サーバー管理権限が必要）")
    @app_commands.describe(user="除外するユーザー")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ignore_add_slash(self, inter: discord.Interaction, user: discord.Member):
        await self._ignore_add(inter, user)

    async def _ignore_add(self, ctx_or_inter, user: discord.Member):
        added = self.guild_settings.add_ignored(_require_guild(ctx_or_inter).id, user.id)
        msg = f"🔕 <@{user.id}> のメッセージを読み上げ対象外にしました。" if added else f"<@{user.id}> はすでに除外されています。"
        await self._send(ctx_or_inter, msg, ephemeral=True)

    @ignore_group.command(name="remove")
    @commands.has_permissions(manage_guild=True)
    async def ignore_remove_prefix(self, ctx: commands.Context, user: discord.Member):
        await self._ignore_remove(ctx, user)

    @ignore_app.command(name="remove", description="ユーザーの読み上げ除外を解除します（サーバー管理権限が必要）")
    @app_commands.describe(user="除外を解除するユーザー")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ignore_remove_slash(self, inter: discord.Interaction, user: discord.Member):
        await self._ignore_remove(inter, user)

    async def _ignore_remove(self, ctx_or_inter, user: discord.Member):
        removed = self.guild_settings.remove_ignored(_require_guild(ctx_or_inter).id, user.id)
        msg = f"🔔 <@{user.id}> の読み上げ除外を解除しました。" if removed else f"<@{user.id}> は除外されていません。"
        await self._send(ctx_or_inter, msg, ephemeral=True)

    @ignore_group.command(name="list")
    @commands.has_permissions(manage_guild=True)
    async def ignore_list_prefix(self, ctx: commands.Context):
        await self._ignore_list(ctx)

    @ignore_app.command(name="list", description="読み上げ除外ユーザーの一覧を表示します（サーバー管理権限が必要）")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ignore_list_slash(self, inter: discord.Interaction):
        await self._ignore_list(inter)

    async def _ignore_list(self, ctx_or_inter):
        ignored = self.guild_settings.ignored_all(_require_guild(ctx_or_inter).id)
        if not ignored:
            msg = "読み上げ除外ユーザーはいません。"
        else:
            lines = "\n".join(f"• <@{uid}>" for uid in sorted(ignored))
            msg = f"🔕 読み上げ除外ユーザー ({len(ignored)}人):\n{lines}"
        await self._send_chunks(ctx_or_inter, msg, ephemeral=True)

    @ignore_group.command(name="me")
    async def ignore_me_prefix(self, ctx: commands.Context):
        await self._ignore_me(ctx)

    @ignore_app.command(name="me", description="自分のメッセージの読み上げ除外を切り替えます")
    async def ignore_me_slash(self, inter: discord.Interaction):
        await self._ignore_me(inter)

    async def _ignore_me(self, ctx_or_inter):
        guild = _require_guild(ctx_or_inter)
        user = ctx_or_inter.user if isinstance(ctx_or_inter, discord.Interaction) else ctx_or_inter.author
        if self.guild_settings.toggle_ignored(guild.id, user.id):
            msg = "🔕 あなたのメッセージを読み上げ対象外にしました。もう一度実行すると戻ります。"
        else:
            msg = "🔔 あなたのメッセージを再び読み上げます。"
        await self._send(ctx_or_inter, msg, ephemeral=True)

    # ------------------------------------------------------------------ #
    # readname（発言者名の読み上げ、管理者向け）
    # ------------------------------------------------------------------ #

    @commands.hybrid_command(name="readname", description="発言者の名前を読み上げるかを切り替えます（サーバー管理権限が必要）")
    @app_commands.describe(enabled="True で名前を読み上げる / False で読み上げない")
    @app_commands.default_permissions(manage_guild=True)
    @commands.has_permissions(manage_guild=True)
    async def readname(self, ctx: commands.Context, enabled: bool):
        self.guild_settings.set_read_name(_require_guild(ctx).id, enabled)
        if enabled:
            await ctx.send("🏷️ 発言者の名前を読み上げます（同じ人の連続投稿では省略）。")
        else:
            await ctx.send("🏷️ 発言者の名前を読み上げないようにしました。")

    # ------------------------------------------------------------------ #
    # Voice state event
    # ------------------------------------------------------------------ #

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if member.bot:
            return
        guild = member.guild
        vc = _voice_client(guild)
        if vc is None:
            await self._maybe_autojoin(member, before, after)
            return

        bot_channel = vc.channel
        name = member.display_name

        if before.channel != bot_channel and after.channel == bot_channel:
            self._cancel_auto_leave(guild.id)
            self._enqueue_announce(guild.id, f"{name}さんが入室しました")
        elif before.channel == bot_channel and after.channel != bot_channel:
            self._enqueue_announce(guild.id, f"{name}さんが退室しました")
            non_bots = [m for m in bot_channel.members if not m.bot]
            if not non_bots:
                self._schedule_auto_leave(guild.id)

    async def _maybe_autojoin(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Bot 未接続時、自動参加に登録された VC に人が入ったら参加する"""
        channel = after.channel
        if channel is None or channel == before.channel:
            return
        guild = member.guild
        text_id = self.guild_settings.autojoin_text(guild.id, channel.id)
        if text_id is None:
            return
        lock = self._autojoin_locks.setdefault(guild.id, asyncio.Lock())
        async with lock:
            # ロック待ちの間に別の入室イベントや /join で接続済みなら何もしない
            if _voice_client(guild) is not None:
                return
            try:
                await self._join_vc(channel)
            except Exception as e:
                print(f"[AUTO-JOIN ERROR] {e}")
                await self.bot.webhook.send(
                    "warning", "自動参加エラー", exc=e,
                    context={"guild_id": str(guild.id), "channel_id": str(channel.id)},
                )
                return
        self.channel_store.add(guild.id, text_id)
        self._enqueue_announce(guild.id, "接続しました")

    # ------------------------------------------------------------------ #
    # Message event
    # ------------------------------------------------------------------ #

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if message.guild is None:
            return
        if message.guild.voice_client is None:
            return
        if not self.channel_store.is_watched(message.guild.id, message.channel.id):
            return
        if self.guild_settings.is_ignored(message.guild.id, message.author.id):
            return

        # コマンド呼び出し（プレフィックスで始まる）は読み上げない
        prefix = self.bot.command_prefix
        if isinstance(prefix, str) and message.content.startswith(prefix):
            return

        guild_id = message.guild.id
        word_dict = self.word_dict.items(guild_id)
        text = filter_message(message.content, word_dict, self.max_length)
        if text is None:
            return

        # 名前読み上げ: 直前と同じ発言者なら省略する
        author_id = message.author.id
        if self.guild_settings.read_name(guild_id) and self._last_author.get(guild_id) != author_id:
            # filter_message の「以下省略」付与を避けるため、名前は自前で切り詰める
            name = filter_message(message.author.display_name, word_dict, max_length=len(message.author.display_name) * 4)
            if name:
                text = f"{name[:_NAME_MAX_LEN]}さん、{text}"
        self._last_author[guild_id] = author_id

        # enqueue時点でスピーカーと速度を解決（後から変更しても影響しない）
        item = TTSItem(
            text=text,
            speaker_id=self.user_voice.get(message.author.id),
            speed=self._guild_speed(message.guild.id),
        )
        self._enqueue_item(message.guild.id, item)

    # ------------------------------------------------------------------ #
    # Admin commands
    # ------------------------------------------------------------------ #

    @commands.hybrid_command(name="reload_speakers", description="スピーカー一覧キャッシュを更新します（VOICEVOX再起動後に使用）")
    @app_commands.default_permissions(manage_guild=True)
    @commands.has_permissions(manage_guild=True)
    async def reload_speakers(self, ctx: commands.Context):
        await ctx.defer(ephemeral=True)
        async with self._speakers_lock:
            self._speakers_cache = None
            self._speaker_id_map = None
        ok = await self._ensure_speakers_cache()
        if ok:
            await ctx.send(f"🔄 スピーカーキャッシュを更新しました（{len(self._speaker_id_map or {})}スタイル）。", ephemeral=True)
        else:
            await ctx.send("⚠️ VOICEVOX に接続できませんでした。ENGINEが起動しているか確認してください。", ephemeral=True)


async def setup(bot: "YomiageBot"):
    cog = TTS(bot)
    await bot.add_cog(cog)
