"""TTS Cog — 読み上げ機能の全コマンドとイベントハンドラ"""

import asyncio
import io
import os

import discord
from discord import app_commands
from discord.ext import commands

from channel_store import ChannelStore, WordDict
from text_filter import filter_message
from voicevox import VoicevoxClient, VoicevoxError


class TTS(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voicevox = VoicevoxClient(os.getenv("VOICEVOX_URL", "http://localhost:50021"))
        self.channel_store = ChannelStore()
        self.word_dict = WordDict()

        self.default_speaker = int(os.getenv("DEFAULT_SPEAKER", "3"))
        self.default_speed = float(os.getenv("DEFAULT_SPEED", "1.0"))
        self.max_length = int(os.getenv("MAX_TEXT_LENGTH", "100"))

        # guild_id → {"speaker": int, "speed": float}
        self._settings: dict[int, dict] = {}

        # guild_id → asyncio.Queue
        self._queues: dict[int, asyncio.Queue] = {}

        # guild_id → asyncio.Task (worker)
        self._workers: dict[int, asyncio.Task] = {}

    async def cog_unload(self):
        await self.voicevox.close()
        for task in self._workers.values():
            task.cancel()

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _guild_settings(self, guild_id: int) -> dict:
        return self._settings.setdefault(
            guild_id, {"speaker": self.default_speaker, "speed": self.default_speed}
        )

    def _get_queue(self, guild_id: int) -> asyncio.Queue:
        if guild_id not in self._queues:
            self._queues[guild_id] = asyncio.Queue()
        return self._queues[guild_id]

    def _ensure_worker(self, guild_id: int):
        task = self._workers.get(guild_id)
        if task is None or task.done():
            self._workers[guild_id] = asyncio.create_task(
                self._tts_worker(guild_id), name=f"tts-worker-{guild_id}"
            )

    async def _tts_worker(self, guild_id: int):
        """キューからテキストを取り出して順番に再生するワーカー"""
        queue = self._get_queue(guild_id)
        while True:
            text = await queue.get()
            try:
                guild = self.bot.get_guild(guild_id)
                if guild is None:
                    continue
                vc: discord.VoiceClient | None = guild.voice_client
                if vc is None or not vc.is_connected():
                    continue

                settings = self._guild_settings(guild_id)
                wav: io.BytesIO = await self.voicevox.synthesis(
                    text, settings["speaker"], settings["speed"]
                )

                # 再生中なら終わるまで待つ（スキップされた場合は即抜ける）
                event = asyncio.Event()
                source = discord.FFmpegPCMAudio(wav, pipe=True)
                vc.play(source, after=lambda _: event.set())
                await event.wait()

            except VoicevoxError as e:
                print(f"[VOICEVOX ERROR] {e}")
            except Exception as e:
                print(f"[TTS WORKER ERROR] {e}")
            finally:
                queue.task_done()

    async def _join_vc(self, ctx_or_inter, voice_channel: discord.VoiceChannel):
        """VCに参加してワーカーを起動する共通処理"""
        guild_id = voice_channel.guild.id
        vc: discord.VoiceClient | None = voice_channel.guild.voice_client

        if vc is not None:
            if vc.channel == voice_channel:
                return vc, False  # already in same channel
            await vc.move_to(voice_channel)
        else:
            vc = await voice_channel.connect()

        self._ensure_worker(guild_id)
        return vc, True

    # ------------------------------------------------------------------ #
    # Commands
    # ------------------------------------------------------------------ #

    @commands.hybrid_command(name="join", description="VCに参加して読み上げを開始します")
    async def join(self, ctx: commands.Context):
        if ctx.author.voice is None:
            await ctx.send("先にボイスチャンネルに参加してください。", ephemeral=True)
            return

        vc, joined = await self._join_vc(ctx, ctx.author.voice.channel)
        guild_id = ctx.guild.id

        # 実行したテキストチャンネルを自動追加
        added = self.channel_store.add(guild_id, ctx.channel.id)

        if joined:
            await ctx.send(
                f"✅ `{ctx.author.voice.channel.name}` に参加しました。\n"
                f"📢 <#{ctx.channel.id}> を読み上げ対象に追加しました。"
            )
        else:
            msg = f"✅ すでに `{vc.channel.name}` にいます。"
            if added:
                msg += f"\n📢 <#{ctx.channel.id}> を読み上げ対象に追加しました。"
            await ctx.send(msg)

    @commands.hybrid_command(name="leave", description="VCから退出して読み上げを停止します")
    async def leave(self, ctx: commands.Context):
        vc: discord.VoiceClient | None = ctx.guild.voice_client
        if vc is None:
            await ctx.send("ボイスチャンネルに接続していません。", ephemeral=True)
            return

        guild_id = ctx.guild.id
        self.channel_store.clear(guild_id)
        self._settings.pop(guild_id, None)

        # キューを空にしてワーカーをキャンセル
        q = self._queues.pop(guild_id, None)
        if q:
            while not q.empty():
                q.get_nowait()
                q.task_done()

        task = self._workers.pop(guild_id, None)
        if task:
            task.cancel()

        await vc.disconnect()
        await ctx.send("👋 退出しました。")

    @commands.hybrid_command(name="skip", description="現在の読み上げをスキップします")
    async def skip(self, ctx: commands.Context):
        vc: discord.VoiceClient | None = ctx.guild.voice_client
        if vc is None or not vc.is_playing():
            await ctx.send("現在再生中の音声はありません。", ephemeral=True)
            return
        vc.stop()
        await ctx.send("⏭️ スキップしました。")

    @commands.hybrid_command(name="voice", description="読み上げスピーカーを変更します")
    @app_commands.describe(speaker_id="VOICEVOX のスピーカーID（例: 3 = ずんだもんノーマル）")
    async def voice(self, ctx: commands.Context, speaker_id: int):
        self._guild_settings(ctx.guild.id)["speaker"] = speaker_id
        await ctx.send(f"🎤 スピーカーを ID `{speaker_id}` に変更しました。")

    @commands.hybrid_command(name="speed", description="読み上げ速度を変更します（0.5〜2.0）")
    @app_commands.describe(value="速度倍率（0.5〜2.0）")
    async def speed(self, ctx: commands.Context, value: float):
        if not 0.5 <= value <= 2.0:
            await ctx.send("速度は 0.5〜2.0 の範囲で指定してください。", ephemeral=True)
            return
        self._guild_settings(ctx.guild.id)["speed"] = value
        await ctx.send(f"⚡ 速度を `{value}` に変更しました。")

    # ------------------------------------------------------------------ #
    # listen サブコマンドグループ
    # ------------------------------------------------------------------ #

    @commands.group(name="listen", invoke_without_command=True)
    async def listen_group(self, ctx: commands.Context):
        await ctx.send_help(ctx.command)

    listen_app = app_commands.Group(name="listen", description="読み上げチャンネルの管理")

    @listen_group.command(name="add")
    @app_commands.describe(channel="追加するテキストチャンネル（省略時は現在のチャンネル）")
    async def listen_add_prefix(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        await self._listen_add(ctx, channel or ctx.channel)

    @listen_app.command(name="add", description="読み上げ対象チャンネルを追加します")
    @app_commands.describe(channel="追加するテキストチャンネル（省略時は現在のチャンネル）")
    async def listen_add_slash(self, inter: discord.Interaction, channel: discord.TextChannel | None = None):
        await self._listen_add(inter, channel or inter.channel)

    async def _listen_add(self, ctx_or_inter, channel: discord.TextChannel):
        guild_id = (ctx_or_inter.guild or ctx_or_inter.guild_id)
        gid = guild_id.id if hasattr(guild_id, "id") else guild_id
        added = self.channel_store.add(gid, channel.id)
        msg = f"📢 <#{channel.id}> を読み上げ対象に追加しました。" if added else f"<#{channel.id}> はすでに登録済みです。"
        if isinstance(ctx_or_inter, discord.Interaction):
            await ctx_or_inter.response.send_message(msg)
        else:
            await ctx_or_inter.send(msg)

    @listen_group.command(name="remove")
    @app_commands.describe(channel="削除するテキストチャンネル（省略時は現在のチャンネル）")
    async def listen_remove_prefix(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        await self._listen_remove(ctx, channel or ctx.channel)

    @listen_app.command(name="remove", description="読み上げ対象チャンネルを削除します")
    @app_commands.describe(channel="削除するテキストチャンネル（省略時は現在のチャンネル）")
    async def listen_remove_slash(self, inter: discord.Interaction, channel: discord.TextChannel | None = None):
        await self._listen_remove(inter, channel or inter.channel)

    async def _listen_remove(self, ctx_or_inter, channel: discord.TextChannel):
        guild_id = ctx_or_inter.guild if isinstance(ctx_or_inter, commands.Context) else ctx_or_inter.guild
        removed = self.channel_store.remove(guild_id.id, channel.id)
        msg = f"🔇 <#{channel.id}> を読み上げ対象から削除しました。" if removed else f"<#{channel.id}> は登録されていません。"
        if isinstance(ctx_or_inter, discord.Interaction):
            await ctx_or_inter.response.send_message(msg)
        else:
            await ctx_or_inter.send(msg)

    @listen_group.command(name="list")
    async def listen_list_prefix(self, ctx: commands.Context):
        await self._listen_list(ctx)

    @listen_app.command(name="list", description="読み上げ対象チャンネル一覧を表示します")
    async def listen_list_slash(self, inter: discord.Interaction):
        await self._listen_list(inter)

    async def _listen_list(self, ctx_or_inter):
        guild = ctx_or_inter.guild
        channels = self.channel_store.get(guild.id)
        if not channels:
            msg = "読み上げ対象のチャンネルが登録されていません。"
        else:
            lines = "\n".join(f"• <#{cid}>" for cid in channels)
            msg = f"📋 読み上げ対象チャンネル:\n{lines}"
        if isinstance(ctx_or_inter, discord.Interaction):
            await ctx_or_inter.response.send_message(msg)
        else:
            await ctx_or_inter.send(msg)

    # ------------------------------------------------------------------ #
    # dict サブコマンドグループ
    # ------------------------------------------------------------------ #

    @commands.group(name="dict", invoke_without_command=True)
    async def dict_group(self, ctx: commands.Context):
        await ctx.send_help(ctx.command)

    dict_app = app_commands.Group(name="dict", description="読み替え辞書の管理")

    @dict_group.command(name="add")
    async def dict_add_prefix(self, ctx: commands.Context, word: str, reading: str):
        self.word_dict.add(word, reading)
        await ctx.send(f"📖 `{word}` → `{reading}` を辞書に追加しました。")

    @dict_app.command(name="add", description="読み替え辞書に単語を追加します")
    @app_commands.describe(word="元の単語", reading="読み替え後のテキスト")
    async def dict_add_slash(self, inter: discord.Interaction, word: str, reading: str):
        self.word_dict.add(word, reading)
        await inter.response.send_message(f"📖 `{word}` → `{reading}` を辞書に追加しました。")

    @dict_group.command(name="remove")
    async def dict_remove_prefix(self, ctx: commands.Context, word: str):
        removed = self.word_dict.remove(word)
        await ctx.send(f"🗑️ `{word}` を削除しました。" if removed else f"`{word}` は辞書にありません。")

    @dict_app.command(name="remove", description="読み替え辞書から単語を削除します")
    @app_commands.describe(word="削除する単語")
    async def dict_remove_slash(self, inter: discord.Interaction, word: str):
        removed = self.word_dict.remove(word)
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
        d = self.word_dict.all()
        if not d:
            msg = "辞書は空です。"
        else:
            lines = "\n".join(f"• `{w}` → `{r}`" for w, r in d.items())
            msg = f"📖 読み替え辞書:\n{lines}"
        if isinstance(ctx_or_inter, discord.Interaction):
            await ctx_or_inter.response.send_message(msg)
        else:
            await ctx_or_inter.send(msg)

    # ------------------------------------------------------------------ #
    # Message event
    # ------------------------------------------------------------------ #

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Bot自身・DM・VCに未接続はスキップ
        if message.author.bot:
            return
        if message.guild is None:
            return
        if message.guild.voice_client is None:
            return
        if not self.channel_store.is_watched(message.guild.id, message.channel.id):
            return

        text = filter_message(message.content, self.word_dict.all(), self.max_length)
        if text is None:
            return

        queue = self._get_queue(message.guild.id)
        await queue.put(text)
        self._ensure_worker(message.guild.id)


async def setup(bot: commands.Bot):
    cog = TTS(bot)
    await bot.add_cog(cog)
    # slash の listen / dict グループを追加
    bot.tree.add_command(cog.listen_app)
    bot.tree.add_command(cog.dict_app)
