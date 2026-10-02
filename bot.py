"""Waras-Yomiage-Bot — VOICEVOX を使った Discord 読み上げBot"""

import asyncio
import os
import sys

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

# 権限名 → 表示名（案内メッセージ用）
_PERMISSION_LABELS = {"manage_guild": "サーバー管理"}


def _user_error_message(error: Exception) -> str | None:
    """ユーザーへ案内すべき操作エラーなら表示用メッセージを返す"""
    if isinstance(error, commands.MissingRequiredArgument):
        return f"⚠️ 引数 `{error.param.name}` が足りません。使い方は `/help` で確認できます。"
    if isinstance(error, commands.BadArgument):
        # ユーザー・チャンネルが見つからない場合や、数値でない値を渡した場合など
        return "⚠️ 引数の形式が正しくないか、指定した対象が見つかりません。使い方は `/help` で確認できます。"
    if isinstance(error, (commands.MissingPermissions, app_commands.MissingPermissions)):
        names = "・".join(_PERMISSION_LABELS.get(p, p) for p in error.missing_permissions)
        return f"⛔ このコマンドを使うには「{names}」権限が必要です。"
    if isinstance(error, (commands.NoPrivateMessage, app_commands.NoPrivateMessage)):
        return "⛔ このコマンドはサーバー内でのみ使えます。"
    return None

# load_dotenv() 後に import することで環境変数を確実に読み込む
from webhook_logger import WebhookLogger  # noqa: E402
from user_store import UserVoiceStore  # noqa: E402
from cogs.uptime_kuma import kuma_heartbeat  # noqa: E402

PREFIX = os.getenv("PREFIX", "!")


class YomiageBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            command_prefix=PREFIX,
            # ユーザー入力を含む返信で @everyone などの通知を飛ばさない（表示は維持される）
            allowed_mentions=discord.AllowedMentions.none(),
            intents=intents,
            help_command=None,  # カスタム help コマンドを使用
        )
        # WebhookLogger は load_dotenv() 後に生成（コンストラクタ内で env を読む）
        self.webhook = WebhookLogger()

        # オーナーユーザーID一覧（OWNER_IDS=id1,id2 形式、未設定時は空）
        raw_owners = os.getenv("OWNER_IDS", "")
        self.owner_ids = frozenset(
            int(x.strip()) for x in raw_owners.split(",") if x.strip().isdigit()
        )

        # UserVoiceStore は TTS / Owner 両 Cog で共有（メモリキャッシュを一元管理）
        default_speaker = int(os.getenv("DEFAULT_SPEAKER", "3"))
        self.user_voice_store = UserVoiceStore(default_speaker=default_speaker)

        # バックグラウンドタスクの参照を保持（GC による途中消失を防ぎ、終了時にキャンセルする）
        self._kuma_task: asyncio.Task[None] | None = None

        # on_ready は再接続（セッション再確立）のたびに呼ばれるため、起動通知は初回のみ
        self._startup_notified = False

    async def setup_hook(self):
        # Cog 読み込み
        try:
            await self.load_extension("cogs.tts")
            await self.load_extension("cogs.utility")
            await self.load_extension("cogs.owner")
            if os.getenv("HEALTH_ENABLED", "false").lower() == "true":
                await self.load_extension("cogs.health")
        except Exception as e:
            await self.webhook.send("error", "Cog 読み込み失敗", exc=e)
            raise

        # GUILD_ID が設定されている場合はギルド限定sync（即時反映）、未設定の場合はグローバルsync
        guild_id_str = os.getenv("GUILD_ID", "")
        try:
            if guild_id_str.isdigit():
                guild = discord.Object(id=int(guild_id_str))
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                print(f"[Bot] スラッシュコマンドをギルド {guild_id_str} に同期しました（即時反映）。")
            else:
                await self.tree.sync()
                print("[Bot] スラッシュコマンドをグローバル同期しました（反映まで最大1時間）。")
        except Exception as e:
            await self.webhook.send("warning", "スラッシュコマンド同期エラー", exc=e)

        # app_commands（スラッシュ）エラーハンドラを登録
        self.tree.on_error = self._on_tree_error

        # Uptime Kuma ハートビート
        if os.getenv("UPTIME_KUMA_PUSH_URL"):
            self._kuma_task = asyncio.create_task(kuma_heartbeat(), name="kuma-heartbeat")

    async def on_ready(self):
        print(f"[Bot] ログイン: {self.user} (ID: {self.user.id if self.user else '-'})")
        print(f"[Bot] プレフィックス: {PREFIX}")

        _status_map = {
            "online":    discord.Status.online,
            "idle":      discord.Status.idle,
            "dnd":       discord.Status.dnd,
            "invisible": discord.Status.invisible,
        }
        raw_status = os.getenv("BOT_STATUS", "online").lower().strip()
        status = _status_map.get(raw_status, discord.Status.online)

        await self.change_presence(
            status=status,
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name=f"{PREFIX}join | /join",
            ),
        )
        if self._startup_notified:
            print("[Bot] 再接続しました（起動通知は送信済み）")
            return
        self._startup_notified = True
        await self.webhook.send(
            "info",
            "Bot 起動",
            context={
                "Bot": str(self.user),
                "サーバー数": str(len(self.guilds)),
                "discord.py": discord.__version__,
                "プレフィックス": PREFIX,
                "ステータス": raw_status,
            },
        )

    async def on_error(self, event: str, *args, **kwargs):
        """イベントハンドラ内の未捕捉例外を通知する"""
        exc = sys.exc_info()[1]
        print(f"[BOT ERROR] イベント '{event}': {exc}")
        await self.webhook.send("error", f"イベントエラー: {event}", exc=exc)

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        """prefix コマンドエラーを通知する（ユーザー操作ミス系は除外）"""
        # CommandInvokeError は original を unwrap して実際の例外を取得
        original = getattr(error, "original", error)
        _ignored = (
            commands.CommandNotFound,
            commands.CheckFailure,
            commands.MissingRequiredArgument,
            commands.BadArgument,
            commands.DisabledCommand,
            commands.NoPrivateMessage,
            commands.MissingPermissions,
        )
        if isinstance(original, _ignored):
            msg = _user_error_message(original)
            if msg:
                try:
                    await ctx.send(msg, ephemeral=True)
                except discord.HTTPException:
                    pass
            return
        print(f"[CMD ERROR] {ctx.command}: {original}")
        await self.webhook.send(
            "error",
            f"コマンドエラー: {ctx.command}",
            exc=original,
            context={
                "サーバー": str(ctx.guild),
                "コマンド": str(ctx.command),
                "ユーザー": str(ctx.author),
            },
        )

    async def _on_tree_error(
        self,
        inter: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        """スラッシュコマンドエラーを通知する（ユーザー操作ミス系は除外）"""
        original = getattr(error, "original", error)
        _ignored = (
            app_commands.CommandNotFound,
            app_commands.CheckFailure,
            app_commands.MissingPermissions,
            app_commands.NoPrivateMessage,
            app_commands.CommandOnCooldown,
        )
        if isinstance(original, _ignored):
            msg = _user_error_message(original)
            if msg:
                try:
                    if inter.response.is_done():
                        await inter.followup.send(msg, ephemeral=True)
                    else:
                        await inter.response.send_message(msg, ephemeral=True)
                except discord.HTTPException:
                    pass
            return
        cmd_name = getattr(inter.command, "name", "不明")
        print(f"[APP CMD ERROR] {cmd_name}: {original}")
        await self.webhook.send(
            "error",
            f"スラッシュコマンドエラー: {cmd_name}",
            exc=original,
            context={
                "サーバー": str(inter.guild),
                "ユーザー": str(inter.user),
            },
        )

    async def close(self):
        """シャットダウン時に Webhook セッションを確実にクローズする"""
        if self._kuma_task and not self._kuma_task.done():
            self._kuma_task.cancel()
            await asyncio.gather(self._kuma_task, return_exceptions=True)
        try:
            await super().close()
        finally:
            await self.webhook.close()


async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise ValueError(".env に DISCORD_TOKEN が設定されていません。")

    bot = YomiageBot()
    try:
        async with bot:
            await bot.start(token)
    except Exception as e:
        # setup_hook 失敗・接続エラーなど起動できなかった場合に通知
        await bot.webhook.send("error", "Bot 起動失敗 / 予期しない終了", exc=e)
        raise


if __name__ == "__main__":
    asyncio.run(main())
