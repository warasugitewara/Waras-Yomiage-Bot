"""TTS Cog — 読み上げ機能の全コマンドとイベントハンドラ（合成・再生は tts_pipeline）"""

import asyncio
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from channel_store import ChannelStore
from config import get_config
from discord_helpers import GuildOnlyCog, send_chunks, send_group_usage, send_response
from discord_helpers import require_guild as _require_guild
from discord_helpers import voice_client_of as _voice_client
from text_filter import filter_message
from tts_pipeline import PlaybackManager, SpeechSynthesizer, TTSItem
from voicevox import VoicevoxClient, VoicevoxError

if TYPE_CHECKING:
    from bot import YomiageBot

# 名前読み上げ時の名前の最大文字数（長い表示名で本文が埋もれないように）
_NAME_MAX_LEN = 20

# キャラクター名だけでは足りない、規約で指定されたクレジット表記
# 出典: https://github.com/VOICEVOX/voicevox_blog/tree/main/src/assets/library-term-intro-markdowns （2026-10-02 確認）
_CREDIT_OVERRIDES = {
    "もち子さん": "VOICEVOX:もち子(cv 明日葉よもぎ)",
    "Voidoll": "VOICEVOX:Voidoll(CV:丹下桜)",
    "ユーレイちゃん": "VOICEVOX:ユーレイちゃん(CV:神崎零)",
    "里石ユカ": "VOICEVOX:里石ユカ（つぼみ）",
}


def credit_for(character: str) -> str:
    """キャラクター名から VOICEVOX のクレジット表記を返す"""
    return _CREDIT_OVERRIDES.get(character, f"VOICEVOX:{character}")


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


class TTS(GuildOnlyCog):
    def __init__(self, bot: "YomiageBot"):
        self.bot = bot
        config = get_config()
        self.voicevox = VoicevoxClient(config.voicevox_url)
        self.channel_store = ChannelStore()
        # 辞書・サーバー設定は Dictionary / ServerSettings Cog と共有するため bot 側で管理
        self.word_dict = bot.word_dict
        self.guild_settings = bot.guild_settings

        self._config = config
        self.default_speaker = config.default_speaker
        self.default_speed = config.default_speed
        self.max_length = config.max_text_length

        # UserVoiceStore は bot 側で管理し、Owner Cog と共有
        self.user_voice = bot.user_voice_store

        # 合成（キャッシュ・合成共有、ギルド横断）と、ギルドごとの再生キュー・ワーカー
        self.synthesizer = SpeechSynthesizer(self.voicevox)
        self.playback = PlaybackManager(bot, self.synthesizer)

        # guild_id → speed(float)
        self._speed: dict[int, float] = {}

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

        # ウォームアップ Task の参照（GC による途中消失を防ぎ、unload 時にキャンセルする）
        self._warmup_task: asyncio.Task[None] | None = None

    async def cog_load(self):
        """Cog 読み込み完了後にウォームアップタスクを起動する"""
        self._warmup_task = asyncio.create_task(self._warmup(), name="voicevox-warmup")

    async def cog_unload(self):
        """シャットダウン: タスクキャンセル → gather → in_flight クリア → セッションクローズ"""
        # 1. 全タスクをキャンセル
        tasks: list[asyncio.Task] = list(self.playback.cancel_all())
        for task in self._auto_leave_tasks.values():
            if not task.done():
                task.cancel()
                tasks.append(task)
        if self._warmup_task and not self._warmup_task.done():
            self._warmup_task.cancel()
            tasks.append(self._warmup_task)

        # 2. 共有合成 Task をキャンセル（完了時コールバックで in_flight から外れる）
        tasks.extend(self.synthesizer.cancel_all())

        # 3. キャンセルが処理されるまで待機（finally ブロックの実行を保証）
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # 4. VoicevoxClient セッションをクローズ（タスク終了後）
        await self.voicevox.close()

    async def _warmup(self):
        """起動後に短文を事前合成してキャッシュ & VOICEVOXエンジンのモデルをウォームアップする"""
        await asyncio.sleep(3)  # Bot接続が安定するまで待機
        try:
            await self.synthesizer.warmup(TTSItem("接続しました", self.default_speaker, self.default_speed))
            print("[TTS] VOICEVOXウォームアップ完了（「接続しました」をキャッシュ）")
        except Exception as e:
            print(f"[TTS] VOICEVOXウォームアップ失敗（起動直後は正常）: {e}")

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _guild_speed(self, guild_id: int) -> float:
        return self._speed.get(guild_id, self.default_speed)

    def _reset_guild_session(self, guild_id: int):
        """VC から退出したときの後片付け（読み上げチャンネル・速度・ワーカーをリセット）"""
        self._cancel_auto_leave(guild_id)
        self.channel_store.clear(guild_id)
        self._speed.pop(guild_id, None)
        self._last_author.pop(guild_id, None)
        self.playback.stop(guild_id)

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
        self._reset_guild_session(guild_id)
        try:
            await vc.disconnect()
        except Exception as e:
            print(f"[AUTO-LEAVE ERROR] {e}")
            await self.bot.webhook.send(
                "warning", "自動退出エラー", exc=e,
                context={"guild_id": str(guild_id)},
            )

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

        self.playback.ensure_workers(guild_id)
        return vc, True

    def _enqueue_announce(self, guild_id: int, text: str):
        """システムアナウンスをデフォルトスピーカーでキューに積む（満杯なら最古を捨てる）"""
        item = TTSItem(
            text=text,
            speaker_id=self.default_speaker,
            speed=self._guild_speed(guild_id),
        )
        self.playback.enqueue(guild_id, item)

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
        return {sid for sid in self._speaker_id_map if self._config.is_speaker_allowed(sid)}

    async def _resolve_speaker_name(self, speaker_id: int) -> str | None:
        """speaker_id から「キャラ名 / スタイル名」の文字列を返す（キャッシュ利用）"""
        if not await self._ensure_speakers_cache() or self._speaker_id_map is None:
            return None
        entry = self._speaker_id_map.get(speaker_id)
        return f"{entry[0]} / {entry[1]}" if entry else None

    def _effective_speaker(self, user_id: int) -> int:
        """ユーザーのボイス設定を返す。運用者が ALLOWED_SPEAKERS で外した ID ならデフォルトに戻す"""
        speaker_id = self.user_voice.get(user_id)
        return speaker_id if self._config.is_speaker_allowed(speaker_id) else self.default_speaker

    async def credits_in_use(self) -> list[str] | None:
        """デフォルトと、ユーザーが設定中のボイスのクレジット表記一覧（/about 用）。ENGINE に接続できなければ None"""
        if not await self._ensure_speakers_cache() or self._speaker_id_map is None:
            return None
        speaker_ids = {self.default_speaker, *self.user_voice.export_all().values()}
        characters = {
            self._speaker_id_map[sid][0]
            for sid in speaker_ids
            if sid in self._speaker_id_map and self._config.is_speaker_allowed(sid)
        }
        return sorted(credit_for(c) for c in characters)

    async def _resolve_credit(self, speaker_id: int) -> str | None:
        """speaker_id から VOICEVOX のクレジット表記（例: VOICEVOX:ずんだもん）を返す"""
        if not await self._ensure_speakers_cache() or self._speaker_id_map is None:
            return None
        entry = self._speaker_id_map.get(speaker_id)
        return credit_for(entry[0]) if entry else None

    async def _send(self, ctx_or_inter, msg: str, ephemeral: bool = False):
        await send_response(ctx_or_inter, msg, ephemeral=ephemeral)

    async def _send_chunks(self, ctx_or_inter, text: str, ephemeral: bool = False):
        await send_chunks(ctx_or_inter, text, ephemeral=ephemeral)

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
        self._reset_guild_session(guild_id)

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

    @commands.hybrid_group(name="myvoice", description="自分の読み上げボイス設定")
    async def myvoice_group(self, ctx: commands.Context):
        await send_group_usage(ctx)

    # --- set ---

    @myvoice_group.command(name="set", description="自分の読み上げボイスを設定します")
    @app_commands.describe(speaker_id="VOICEVOX のスピーカーID（/myvoice list で確認）")
    async def myvoice_set_prefix(self, ctx: commands.Context, speaker_id: int):
        await ctx.defer()
        await self._myvoice_set(ctx, speaker_id)

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

    @myvoice_group.command(name="reset", description="自分のボイス設定をデフォルト（ずんだもん ノーマル）に戻します")
    async def myvoice_reset_prefix(self, ctx: commands.Context):
        await ctx.defer()
        await self._myvoice_reset(ctx)

    async def _myvoice_reset(self, ctx_or_inter):
        user_id = (
            ctx_or_inter.author.id
            if isinstance(ctx_or_inter, commands.Context)
            else ctx_or_inter.user.id
        )
        self.user_voice.reset(user_id)
        await self._send(ctx_or_inter, f"🔄 ボイスをデフォルト（ID `{self.default_speaker}`）にリセットしました。")

    # --- info ---

    @myvoice_group.command(name="info", description="現在の自分のボイス設定を表示します")
    async def myvoice_info_prefix(self, ctx: commands.Context):
        await ctx.defer(ephemeral=True)
        await self._myvoice_info(ctx)

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

    @myvoice_group.command(name="list", description="利用可能なスピーカー一覧を表示します")
    async def myvoice_list_prefix(self, ctx: commands.Context):
        await ctx.defer(ephemeral=True)
        await self._myvoice_list(ctx)

    async def _myvoice_list(self, ctx_or_inter):
        if not await self._ensure_speakers_cache():
            await self._send(ctx_or_inter, "⚠️ VOICEVOX に接続できません。", ephemeral=True)
            return

        lines = ["🎤 **利用可能なスピーカー一覧**\n"]
        for sp in self._speakers_cache or []:
            if not any(self._config.is_speaker_allowed(s["id"]) for s in sp["styles"]):
                continue
            styles = " | ".join(
                f"{s['name']}: `{s['id']}`" for s in sp["styles"] if self._config.is_speaker_allowed(s["id"])
            )
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

    @commands.hybrid_group(name="listen", description="読み上げチャンネルの管理")
    async def listen_group(self, ctx: commands.Context):
        await send_group_usage(ctx)

    @listen_group.command(name="add", description="読み上げ対象チャンネルを追加します")
    @app_commands.describe(channel="追加するテキストチャンネル（省略時は現在のチャンネル）")
    async def listen_add_prefix(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        await self._listen_add(ctx, channel or ctx.channel)

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

    @listen_group.command(name="remove", description="読み上げ対象チャンネルを削除します")
    @app_commands.describe(channel="削除するテキストチャンネル（省略時は現在のチャンネル）")
    async def listen_remove_prefix(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        await self._listen_remove(ctx, channel or ctx.channel)

    async def _listen_remove(self, ctx_or_inter, channel: discord.abc.Snowflake | None):
        if channel is None:
            await self._send(ctx_or_inter, "⚠️ チャンネルを特定できませんでした。", ephemeral=True)
            return
        guild = ctx_or_inter.guild
        removed = self.channel_store.remove(guild.id, channel.id)
        msg = f"🔇 <#{channel.id}> を読み上げ対象から削除しました。" if removed else f"<#{channel.id}> は登録されていません。"
        await self._send(ctx_or_inter, msg)

    @listen_group.command(name="list", description="読み上げ対象チャンネル一覧を表示します")
    async def listen_list_prefix(self, ctx: commands.Context):
        await self._listen_list(ctx)

    async def _listen_list(self, ctx_or_inter):
        channels = self.channel_store.get(ctx_or_inter.guild.id)
        if not channels:
            msg = "読み上げ対象のチャンネルが登録されていません。"
        else:
            lines = "\n".join(f"• <#{cid}>" for cid in channels)
            msg = f"📋 読み上げ対象チャンネル:\n{lines}"
        await self._send(ctx_or_inter, msg)

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
        if self.bot.user is not None and member.id == self.bot.user.id:
            # 管理者による切断など、/leave 以外で Bot が VC から外れた場合も状態を片付ける
            if before.channel is not None and after.channel is None:
                self._reset_guild_session(member.guild.id)
            return
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

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        """サーバーから退出・キックされたら、そのサーバーのデータを削除する"""
        guild_id = guild.id
        self._cancel_auto_leave(guild_id)
        self.playback.stop(guild_id)
        self._speed.pop(guild_id, None)
        self._last_author.pop(guild_id, None)
        self._autojoin_locks.pop(guild_id, None)
        self.channel_store.clear(guild_id)
        self.word_dict.clear(guild_id)
        self.guild_settings.clear(guild_id)
        print(f"[GUILD REMOVE] サーバー {guild_id} のデータを削除しました")

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
            speaker_id=self._effective_speaker(message.author.id),
            speed=self._guild_speed(message.guild.id),
        )
        self.playback.enqueue(message.guild.id, item)

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
