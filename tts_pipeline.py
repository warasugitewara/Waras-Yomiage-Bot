"""読み上げの合成・再生パイプライン

- SpeechSynthesizer: VOICEVOX 合成 → PCM 変換、LRU キャッシュ、同一テキストの合成の共有（ギルド横断）
- PlaybackManager:   ギルドごとのメッセージキュー・PCM キューと、合成ワーカー・再生ワーカー
"""

import asyncio
import collections
import io
import time
import wave
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import discord

from discord_helpers import voice_client_of
from voicevox import VoicevoxEngineError, VoicevoxError

if TYPE_CHECKING:
    from bot import YomiageBot

# PCM キャッシュの上限（48kHz stereo s16le は 1秒あたり約 192KB）
PCM_CACHE_MAX = 100
PCM_CACHE_MAX_BYTES = 64 * 1024 * 1024

# VOICEVOX への同時合成リクエスト数（ギルド数が増えてもエンジン VM を過負荷にしない）
SYNTH_CONCURRENCY = 2
# 予備 ENGINE（CPU 版）への同時合成リクエスト数（CPU 合成は遅く、並べても速くならない）
FALLBACK_SYNTH_CONCURRENCY = 1

# 主 ENGINE で 5xx になった声を、予備 ENGINE へ直接回す時間（秒）。
# 主 ENGINE で失敗するのを毎回待たないため。期限が切れたら主 ENGINE を再び試す
PRIMARY_AVOID_SECONDS = 600.0

# ギルドごとのキュー長（メッセージは満杯なら最古を捨てる。PCM は2件まで先読み）
_MESSAGE_QUEUE_MAX = 50
_PCM_QUEUE_MAX = 2

CacheKey = tuple[str, int, float]

# フォールバックの通知先（タイトル, 本文）
FallbackNotifier = Callable[[str, str], Awaitable[None]]


class SynthesisEngine(Protocol):
    """合成に使う ENGINE（VoicevoxClient が満たす）"""

    async def synthesis(self, text: str, speaker: int, speed: float = 1.0) -> bytes: ...


@dataclass
class TTSItem:
    """キューに積む読み上げ1件分のデータ（enqueue時点で解決済み）"""
    text: str
    speaker_id: int
    speed: float

    @property
    def cache_key(self) -> CacheKey:
        return (self.text, self.speaker_id, self.speed)


def extract_discord_pcm(wav_bytes: bytes) -> bytes | None:
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


async def wav_to_pcm(wav_bytes: bytes) -> bytes:
    """VOICEVOX出力WAVをDiscord用PCM(48kHz stereo s16le)に変換する。
    VOICEVOX に 48kHz stereo を指定しているため通常はヘッダ除去のみで済む。
    それ以外の形式（旧エンジン等）の場合のみ FFmpeg で変換する。
    変換は合成時に1回だけ実行し、結果をキャッシュする。
    再生ワーカーは discord.PCMAudio で直接再生するため FFmpeg プロセスを起動しない。

    ffmpeg が異常終了した場合や出力が空の場合は RuntimeError を送出する。
    これを怠ると空の PCM がキャッシュに保存され、同じテキストが以後ずっと
    無音再生になってしまう。
    """
    pcm = extract_discord_pcm(wav_bytes)
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


class SpeechSynthesizer:
    """テキストを Discord 再生用 PCM に変換する（キャッシュ・合成共有つき、ギルド横断で1つ）

    合成は次の順に試す（fallback 未設定なら 2 を飛ばす）:
      1. 主 ENGINE（GPU）で指定の声
      2. 予備 ENGINE（CPU）で指定の声
      3. 主 ENGINE で既定の声（default_speaker）
    3 で読んだ音声は指定の声の結果ではないため、キャッシュしない。
    """

    def __init__(
        self,
        voicevox: SynthesisEngine,
        fallback: SynthesisEngine | None = None,
        default_speaker: int | None = None,
        notify: FallbackNotifier | None = None,
    ):
        self.voicevox = voicevox
        self.fallback = fallback
        self.default_speaker = default_speaker
        self._notify = notify
        # speaker_id → 主 ENGINE を避ける期限（time.monotonic()）
        self._primary_avoid_until: dict[int, float] = {}

        # PCM LRU キャッシュ (text, speaker_id, speed) → 48kHz stereo s16le bytes
        # キャッシュヒット時は VOICEVOX 合成・変換のいずれも省略
        self.cache: collections.OrderedDict[CacheKey, bytes] = collections.OrderedDict()
        self.cache_bytes = 0

        # in-flight dedup: 合成中キーを共有 Task で管理（ギルド横断共有）
        # 同じ (text, speaker_id, speed) が既に合成中なら Task を shield して待つ。
        # Task はどのギルドのワーカーにも所有されないため、/leave でワーカーが
        # キャンセルされても合成は継続し、他ギルドの待機が停止しない
        self.in_flight: dict[CacheKey, asyncio.Task[bytes]] = {}
        self._sem = asyncio.Semaphore(SYNTH_CONCURRENCY)
        self._fallback_sem = asyncio.Semaphore(FALLBACK_SYNTH_CONCURRENCY)

    def cached(self, key: CacheKey) -> bytes | None:
        """キャッシュにあれば返し、LRU の最新に移す（await を挟まないので安全）"""
        pcm = self.cache.get(key)
        if pcm is not None:
            self.cache.move_to_end(key)
        return pcm

    async def synthesize(self, item: TTSItem) -> bytes:
        """item の PCM を返す。キャッシュ → 合成中の共有 Task → 新規合成の順に使う。
        shield により呼び出し側のキャンセルは共有 Task へ伝播しない。
        """
        pcm = self.cached(item.cache_key)
        if pcm is not None:
            return pcm
        return await asyncio.shield(self.get_or_start(item))

    def get_or_start(self, item: TTSItem) -> asyncio.Task[bytes]:
        """item の共有合成 Task を返す。未開始なら開始する"""
        key = item.cache_key
        task = self.in_flight.get(key)
        if task is None:
            task = asyncio.create_task(self._synthesize(item), name="tts-shared-synthesis")
            self.in_flight[key] = task
            task.add_done_callback(lambda t, k=key: self._on_done(k, t))
        return task

    def _on_done(self, key: CacheKey, task: asyncio.Task[bytes]) -> None:
        if self.in_flight.get(key) is task:
            del self.in_flight[key]
        # 待機ワーカーが全員キャンセル済みでも "exception was never retrieved" を出さない
        if not task.cancelled():
            task.exception()

    async def _synthesize(self, item: TTSItem) -> bytes:
        """VOICEVOX 合成 → PCM 変換し、キャッシュへ保存して返す"""
        wav_bytes, exact = await self._synthesize_wav(item)
        pcm_bytes = await wav_to_pcm(wav_bytes)
        # キャッシュ更新（VC切断に関わらず次回のために保存）。既定の声で代わりに読んだ音声は
        # 保存しない（保存すると、その文がキャッシュから消えるまで既定の声のままになる）
        if exact:
            self.cache_put(item.cache_key, pcm_bytes)
        return pcm_bytes

    def _primary_avoided(self, speaker_id: int) -> bool:
        until = self._primary_avoid_until.get(speaker_id)
        if until is None:
            return False
        if time.monotonic() >= until:
            del self._primary_avoid_until[speaker_id]
            return False
        return True

    async def _synthesize_wav(self, item: TTSItem) -> tuple[bytes, bool]:
        """フォールバック順に合成し、(WAV, 指定の声で合成できたか) を返す。
        すべて失敗したら最後のエラーを送出する。
        """
        speaker = item.speaker_id
        errors: list[str] = []
        # 主 ENGINE が接続エラー・タイムアウトなら、既定の声で再試行しても無駄なので飛ばす
        primary_reachable = True

        if self.fallback is None or not self._primary_avoided(speaker):
            try:
                async with self._sem:
                    return await self.voicevox.synthesis(item.text, speaker, item.speed), True
            except VoicevoxEngineError as e:
                errors.append(f"主 ENGINE: {e}")
                if self.fallback is not None:
                    self._primary_avoid_until[speaker] = time.monotonic() + PRIMARY_AVOID_SECONDS
                    await self._report(
                        "VOICEVOX 主 ENGINE で合成失敗",
                        f"speaker={speaker} を {int(PRIMARY_AVOID_SECONDS // 60)} 分間 予備 ENGINE で合成します: {e}",
                    )
            except VoicevoxError as e:
                errors.append(f"主 ENGINE: {e}")
                primary_reachable = False

        if self.fallback is not None:
            try:
                async with self._fallback_sem:
                    return await self.fallback.synthesis(item.text, speaker, item.speed), True
            except VoicevoxError as e:
                errors.append(f"予備 ENGINE: {e}")

        default = self.default_speaker
        if default is not None and default != speaker and primary_reachable:
            try:
                async with self._sem:
                    wav = await self.voicevox.synthesis(item.text, default, item.speed)
            except VoicevoxError as e:
                errors.append(f"既定の声: {e}")
            else:
                await self._report(
                    "VOICEVOX 既定の声で代替",
                    f"speaker={speaker} を合成できず、既定の声（speaker={default}）で読みました: "
                    + " / ".join(errors),
                )
                return wav, False

        raise VoicevoxError(" / ".join(errors) or "VOICEVOX 合成に失敗しました")

    async def _report(self, title: str, description: str) -> None:
        print(f"[VOICEVOX FALLBACK] {title}: {description}")
        if self._notify is not None:
            try:
                await self._notify(title, description)
            except Exception as e:  # 通知の失敗で読み上げを止めない
                print(f"[VOICEVOX FALLBACK] 通知に失敗: {e}")

    def cache_put(self, key: CacheKey, pcm: bytes) -> None:
        """PCM を LRU キャッシュに保存し、件数・合計バイト数の上限まで古い順に破棄する"""
        old = self.cache.pop(key, None)
        if old is not None:
            self.cache_bytes -= len(old)
        if len(pcm) > PCM_CACHE_MAX_BYTES:
            return  # 単体で上限を超える音声はキャッシュしない
        self.cache[key] = pcm
        self.cache_bytes += len(pcm)
        while len(self.cache) > PCM_CACHE_MAX or self.cache_bytes > PCM_CACHE_MAX_BYTES:
            _, evicted = self.cache.popitem(last=False)
            self.cache_bytes -= len(evicted)

    async def warmup(self, item: TTSItem) -> None:
        """起動直後に1件合成してキャッシュし、VOICEVOX エンジンのモデルを温める"""
        if item.cache_key in self.cache:
            return
        wav = await self.voicevox.synthesis(item.text, item.speaker_id, item.speed)
        self.cache_put(item.cache_key, await wav_to_pcm(wav))

    def cancel_all(self) -> list[asyncio.Task[bytes]]:
        """共有合成 Task をキャンセルし、完了待ち用に返す（完了時コールバックで in_flight から外れる）"""
        tasks = [t for t in self.in_flight.values() if not t.done()]
        for t in tasks:
            t.cancel()
        return tasks


class PlaybackManager:
    """ギルドごとの読み上げキューと、合成ワーカー・再生ワーカーを管理する"""

    def __init__(self, bot: "YomiageBot", synthesizer: SpeechSynthesizer):
        self.bot = bot
        self.synthesizer = synthesizer

        # guild_id → asyncio.Queue[TTSItem]  (メッセージキュー)
        self._queues: dict[int, asyncio.Queue[TTSItem]] = {}

        # guild_id → asyncio.Queue[bytes]  (再生待ちPCMキュー、最大2件先読み)
        self._pcm_queues: dict[int, asyncio.Queue[bytes]] = {}

        # guild_id → (synthesizer_task, player_task)
        self._workers: dict[int, tuple[asyncio.Task[None] | None, asyncio.Task[None] | None]] = {}

    def message_queue(self, guild_id: int) -> asyncio.Queue[TTSItem]:
        if guild_id not in self._queues:
            self._queues[guild_id] = asyncio.Queue(maxsize=_MESSAGE_QUEUE_MAX)
        return self._queues[guild_id]

    def pcm_queue(self, guild_id: int) -> asyncio.Queue[bytes]:
        if guild_id not in self._pcm_queues:
            self._pcm_queues[guild_id] = asyncio.Queue(maxsize=_PCM_QUEUE_MAX)
        return self._pcm_queues[guild_id]

    def enqueue(self, guild_id: int, item: TTSItem) -> None:
        """メッセージキューに積む（満杯なら最古を捨てる）"""
        q = self.message_queue(guild_id)
        if q.full():
            try:
                q.get_nowait()
                # 捨てた要素も処理済みとして数え、未完了カウンタのずれを防ぐ
                q.task_done()
            except asyncio.QueueEmpty:
                pass
        q.put_nowait(item)
        self.ensure_workers(guild_id)

    def ensure_workers(self, guild_id: int) -> None:
        synth, play = self._workers.get(guild_id, (None, None))
        if synth is None or synth.done():
            synth = asyncio.create_task(self.synthesis_worker(guild_id), name=f"synth-{guild_id}")
        if play is None or play.done():
            play = asyncio.create_task(self.player_worker(guild_id), name=f"player-{guild_id}")
        self._workers[guild_id] = (synth, play)

    def stop(self, guild_id: int) -> None:
        """合成ワーカーと再生ワーカーをキャンセルしてキューを空にする"""
        synth, play = self._workers.pop(guild_id, (None, None))
        if synth:
            synth.cancel()
        if play:
            play.cancel()
        queues: tuple[asyncio.Queue[TTSItem] | None, asyncio.Queue[bytes] | None] = (
            self._queues.pop(guild_id, None),
            self._pcm_queues.pop(guild_id, None),
        )
        for q in queues:
            if q:
                while not q.empty():
                    try:
                        q.get_nowait()
                        q.task_done()
                    except Exception:
                        pass

    def cancel_all(self) -> list[asyncio.Task[None]]:
        """全ギルドのワーカーをキャンセルし、完了待ち用に返す"""
        tasks: list[asyncio.Task[None]] = []
        for synth, play in self._workers.values():
            for task in (synth, play):
                if task and not task.done():
                    task.cancel()
                    tasks.append(task)
        return tasks

    async def synthesis_worker(self, guild_id: int) -> None:
        """メッセージキューからTTSItemを取り出し、PCMに変換してPCMキューに積む"""
        msg_q = self.message_queue(guild_id)
        pcm_q = self.pcm_queue(guild_id)
        while True:
            item = await msg_q.get()
            try:
                guild = self.bot.get_guild(guild_id)
                if guild is None or guild.voice_client is None:
                    continue

                pcm_bytes = await self.synthesizer.synthesize(item)

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

    async def player_worker(self, guild_id: int) -> None:
        """PCMキューから音声を取り出してVCで直接再生する（FFmpegプロセス不要）"""
        pcm_q = self.pcm_queue(guild_id)
        loop = asyncio.get_running_loop()
        while True:
            pcm = await pcm_q.get()
            try:
                guild = self.bot.get_guild(guild_id)
                vc = voice_client_of(guild) if guild else None
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
