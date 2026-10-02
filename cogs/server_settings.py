"""ServerSettings Cog — 自動参加（/autojoin）・読み上げ除外（/ignore）・名前読み上げ（/readname）"""

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from discord_helpers import GuildOnlyCog, require_guild, send_chunks, send_group_usage, send_response

if TYPE_CHECKING:
    from bot import YomiageBot


class ServerSettings(GuildOnlyCog):
    def __init__(self, bot: "YomiageBot"):
        self.bot = bot
        self.guild_settings = bot.guild_settings

    # ------------------------------------------------------------------ #
    # autojoin サブコマンドグループ（管理者向け）
    # ------------------------------------------------------------------ #

    @commands.hybrid_group(name="autojoin", description="VC への自動参加の管理（サーバー管理権限が必要）")
    @app_commands.default_permissions(manage_guild=True)
    async def autojoin_group(self, ctx: commands.Context):
        await send_group_usage(ctx)

    @autojoin_group.command(name="add", description="人が入ったら自動参加する VC を登録します")
    @app_commands.describe(
        vc="自動参加するボイスチャンネル",
        text="読み上げるテキストチャンネル（省略時は VC 内チャット）",
    )
    @commands.has_permissions(manage_guild=True)
    async def autojoin_add_prefix(
        self,
        ctx: commands.Context,
        vc: discord.VoiceChannel,
        text: discord.TextChannel | None = None,
    ):
        await self._autojoin_add(ctx, vc, text)

    async def _autojoin_add(self, ctx_or_inter, vc: discord.VoiceChannel, text: discord.TextChannel | None):
        guild = require_guild(ctx_or_inter)
        perms = vc.permissions_for(guild.me)
        if not (perms.connect and perms.speak):
            await send_response(ctx_or_inter, f"⚠️ <#{vc.id}> に接続・発言する権限が Bot にありません。", ephemeral=True)
            return
        # テキストチャンネル未指定時は VC 内チャット（VC と同じ ID）を読み上げる
        text_id = text.id if text else vc.id
        self.guild_settings.set_autojoin(guild.id, vc.id, text_id)
        await send_response(ctx_or_inter, f"🔁 <#{vc.id}> に人が入ったら自動参加し、<#{text_id}> を読み上げます。")

    @autojoin_group.command(name="remove", description="自動参加 VC の登録を解除します")
    @app_commands.describe(vc="解除するボイスチャンネル")
    @commands.has_permissions(manage_guild=True)
    async def autojoin_remove_prefix(self, ctx: commands.Context, vc: discord.VoiceChannel):
        await self._autojoin_remove(ctx, vc)

    async def _autojoin_remove(self, ctx_or_inter, vc: discord.VoiceChannel):
        removed = self.guild_settings.remove_autojoin(require_guild(ctx_or_inter).id, vc.id)
        msg = f"🛑 <#{vc.id}> の自動参加を解除しました。" if removed else f"<#{vc.id}> は自動参加に登録されていません。"
        await send_response(ctx_or_inter, msg)

    @autojoin_group.command(name="list", description="自動参加 VC の一覧を表示します")
    @commands.has_permissions(manage_guild=True)
    async def autojoin_list_prefix(self, ctx: commands.Context):
        await self._autojoin_list(ctx)

    async def _autojoin_list(self, ctx_or_inter):
        entries = self.guild_settings.autojoin_all(require_guild(ctx_or_inter).id)
        if not entries:
            msg = "自動参加する VC は登録されていません。"
        else:
            lines = "\n".join(f"• <#{vc_id}> → <#{text_id}>" for vc_id, text_id in entries.items())
            msg = f"🔁 自動参加 VC（VC → 読み上げ先）:\n{lines}"
        await send_chunks(ctx_or_inter, msg)

    # ------------------------------------------------------------------ #
    # ignore サブコマンドグループ（読み上げ除外ユーザー）
    # ------------------------------------------------------------------ #

    @commands.hybrid_group(name="ignore", description="読み上げ除外ユーザーの管理")
    async def ignore_group(self, ctx: commands.Context):
        await send_group_usage(ctx)

    @ignore_group.command(name="add", description="ユーザーのメッセージを読み上げ対象外にします（サーバー管理権限が必要）")
    @app_commands.describe(user="除外するユーザー")
    @commands.has_permissions(manage_guild=True)
    async def ignore_add_prefix(self, ctx: commands.Context, user: discord.Member):
        await self._ignore_add(ctx, user)

    async def _ignore_add(self, ctx_or_inter, user: discord.Member):
        added = self.guild_settings.add_ignored(require_guild(ctx_or_inter).id, user.id)
        msg = f"🔕 <@{user.id}> のメッセージを読み上げ対象外にしました。" if added else f"<@{user.id}> はすでに除外されています。"
        await send_response(ctx_or_inter, msg, ephemeral=True)

    @ignore_group.command(name="remove", description="ユーザーの読み上げ除外を解除します（サーバー管理権限が必要）")
    @app_commands.describe(user="除外を解除するユーザー")
    @commands.has_permissions(manage_guild=True)
    async def ignore_remove_prefix(self, ctx: commands.Context, user: discord.Member):
        await self._ignore_remove(ctx, user)

    async def _ignore_remove(self, ctx_or_inter, user: discord.Member):
        removed = self.guild_settings.remove_ignored(require_guild(ctx_or_inter).id, user.id)
        msg = f"🔔 <@{user.id}> の読み上げ除外を解除しました。" if removed else f"<@{user.id}> は除外されていません。"
        await send_response(ctx_or_inter, msg, ephemeral=True)

    @ignore_group.command(name="list", description="読み上げ除外ユーザーの一覧を表示します（サーバー管理権限が必要）")
    @commands.has_permissions(manage_guild=True)
    async def ignore_list_prefix(self, ctx: commands.Context):
        await self._ignore_list(ctx)

    async def _ignore_list(self, ctx_or_inter):
        ignored = self.guild_settings.ignored_all(require_guild(ctx_or_inter).id)
        if not ignored:
            msg = "読み上げ除外ユーザーはいません。"
        else:
            lines = "\n".join(f"• <@{uid}>" for uid in sorted(ignored))
            msg = f"🔕 読み上げ除外ユーザー ({len(ignored)}人):\n{lines}"
        await send_chunks(ctx_or_inter, msg, ephemeral=True)

    @ignore_group.command(name="me", description="自分のメッセージの読み上げ除外を切り替えます")
    async def ignore_me_prefix(self, ctx: commands.Context):
        await self._ignore_me(ctx)

    async def _ignore_me(self, ctx_or_inter):
        guild = require_guild(ctx_or_inter)
        user = ctx_or_inter.user if isinstance(ctx_or_inter, discord.Interaction) else ctx_or_inter.author
        if self.guild_settings.toggle_ignored(guild.id, user.id):
            msg = "🔕 あなたのメッセージを読み上げ対象外にしました。もう一度実行すると戻ります。"
        else:
            msg = "🔔 あなたのメッセージを再び読み上げます。"
        await send_response(ctx_or_inter, msg, ephemeral=True)

    # ------------------------------------------------------------------ #
    # readname（発言者名の読み上げ、管理者向け）
    # ------------------------------------------------------------------ #

    @commands.hybrid_command(name="readname", description="発言者の名前を読み上げるかを切り替えます（サーバー管理権限が必要）")
    @app_commands.describe(enabled="True で名前を読み上げる / False で読み上げない")
    @app_commands.default_permissions(manage_guild=True)
    @commands.has_permissions(manage_guild=True)
    async def readname(self, ctx: commands.Context, enabled: bool):
        self.guild_settings.set_read_name(require_guild(ctx).id, enabled)
        if enabled:
            await ctx.send("🏷️ 発言者の名前を読み上げます（同じ人の連続投稿では省略）。")
        else:
            await ctx.send("🏷️ 発言者の名前を読み上げないようにしました。")


async def setup(bot: "YomiageBot"):
    await bot.add_cog(ServerSettings(bot))
