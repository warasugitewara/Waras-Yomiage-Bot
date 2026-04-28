"""Owner Cog — オーナー専用コマンド（ユーザー設定 export/import 等）"""

import io
import json

import discord
from discord import app_commands
from discord.ext import commands


class Owner(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── ガードヘルパー ────────────────────────────────────────────────────

    async def _check_owner(self, ctx_or_inter) -> bool:
        """オーナー確認。非オーナーまたは未設定の場合はメッセージを送り False を返す。"""
        if isinstance(ctx_or_inter, commands.Context):
            uid = ctx_or_inter.author.id
        else:
            uid = ctx_or_inter.user.id

        if not self.bot.owner_ids:
            msg = "⛔ オーナーが登録されていません。`.env` に `OWNER_IDS` を設定してください。"
        elif uid not in self.bot.owner_ids:
            msg = "⛔ このコマンドはオーナーのみ使用できます。"
        else:
            return True

        if isinstance(ctx_or_inter, discord.Interaction):
            if ctx_or_inter.response.is_done():
                await ctx_or_inter.followup.send(msg, ephemeral=True)
            else:
                await ctx_or_inter.response.send_message(msg, ephemeral=True)
        else:
            await ctx_or_inter.send(msg)
        return False

    # ── prefix コマンドグループ ────────────────────────────────────────────

    @commands.group(name="owner", invoke_without_command=True)
    async def owner_group(self, ctx: commands.Context):
        if not await self._check_owner(ctx):
            return
        await ctx.send_help(ctx.command)

    # ── slash コマンドグループ ─────────────────────────────────────────────

    owner_app = app_commands.Group(name="owner", description="オーナー専用コマンド")

    # ── export_users ──────────────────────────────────────────────────────

    @owner_group.command(name="export_users", help="全ユーザーのボイス設定をJSONでエクスポートします")
    async def export_users_prefix(self, ctx: commands.Context):
        if not await self._check_owner(ctx):
            return
        await ctx.defer()
        await self._export_users(ctx)

    @owner_app.command(name="export_users", description="全ユーザーのボイス設定をJSONでエクスポートします（オーナーのみ）")
    async def export_users_slash(self, inter: discord.Interaction):
        if not await self._check_owner(inter):
            return
        await inter.response.defer(ephemeral=True)
        await self._export_users(inter)

    async def _export_users(self, ctx_or_inter):
        data = self.bot.user_voice_store.export_all()
        payload = {
            "version": 1,
            "data": [
                {"user_id": uid, "speaker_id": spk}
                for uid, spk in data.items()
            ],
        }
        buf = io.BytesIO(json.dumps(payload, ensure_ascii=False, indent=2).encode())
        buf.seek(0)
        file = discord.File(buf, filename="users.json")
        msg = f"📤 ユーザー設定をエクスポートしました（{len(data)}件）"
        if isinstance(ctx_or_inter, discord.Interaction):
            await ctx_or_inter.followup.send(msg, file=file, ephemeral=True)
        else:
            await ctx_or_inter.send(msg, file=file)

    # ── import_users ──────────────────────────────────────────────────────

    @owner_group.command(name="import_users", help="JSONファイルからユーザーのボイス設定をインポートします")
    async def import_users_prefix(self, ctx: commands.Context, replace: bool = False):
        if not await self._check_owner(ctx):
            return
        if not ctx.message.attachments:
            await ctx.send("⚠️ JSONファイルを添付してください。")
            return
        await ctx.defer()
        await self._import_users(ctx, ctx.message.attachments[0], replace)

    @owner_app.command(name="import_users", description="JSONファイルからユーザーのボイス設定をインポートします（オーナーのみ）")
    @app_commands.describe(
        file="インポートするJSONファイル",
        replace="True で既存設定を全置換（デフォルト: False でマージ）",
    )
    async def import_users_slash(
        self,
        inter: discord.Interaction,
        file: discord.Attachment,
        replace: bool = False,
    ):
        if not await self._check_owner(inter):
            return
        await inter.response.defer(ephemeral=True)
        await self._import_users(inter, file, replace)

    async def _import_users(self, ctx_or_inter, attachment: discord.Attachment, replace: bool):
        if not attachment.filename.endswith(".json"):
            await self._send(ctx_or_inter, "⚠️ `.json` ファイルのみ対応しています。")
            return
        try:
            raw_bytes = await attachment.read()
            data = json.loads(raw_bytes.decode("utf-8"))
        except Exception:
            await self._send(ctx_or_inter, "⚠️ JSONの読み込みに失敗しました。")
            return

        entries = self._parse_users_json(data)
        if entries is None:
            await self._send(
                ctx_or_inter,
                "⚠️ サポートされていないJSONフォーマットです。\n"
                "`{\"version\":1, \"data\":[{\"user_id\":\"123\", \"speaker_id\":3},...]}` 形式を使用してください。",
            )
            return

        count = self.bot.user_voice_store.import_all(entries, replace=replace)
        mode = "全置換" if replace else "マージ"
        await self._send(ctx_or_inter, f"📥 ユーザー設定を{mode}でインポートしました（{count}件）。")

    @staticmethod
    def _parse_users_json(data: dict) -> dict[str, int] | None:
        """JSONを {user_id_str: speaker_id_int} に変換する。無効エントリはスキップ。"""
        if not isinstance(data, dict):
            return None

        if "data" in data and isinstance(data["data"], list):
            result = {}
            for item in data["data"]:
                if not isinstance(item, dict):
                    continue
                uid = item.get("user_id")
                spk = item.get("speaker_id")
                # バリデーション: user_id は数字文字列、speaker_id は整数
                if not (isinstance(uid, str) and uid.isdigit()):
                    continue
                if not isinstance(spk, int):
                    continue
                result[uid] = spk
            return result

        return None

    async def _send(self, ctx_or_inter, msg: str):
        if isinstance(ctx_or_inter, discord.Interaction):
            if ctx_or_inter.response.is_done():
                await ctx_or_inter.followup.send(msg, ephemeral=True)
            else:
                await ctx_or_inter.response.send_message(msg, ephemeral=True)
        else:
            await ctx_or_inter.send(msg)


async def setup(bot: commands.Bot):
    cog = Owner(bot)
    await bot.add_cog(cog)
