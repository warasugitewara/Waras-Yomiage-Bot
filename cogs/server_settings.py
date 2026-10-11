"""ServerSettings Cog — 自動参加（/autojoin）・読み上げ除外（/ignore）・名前読み上げ（/readname）"""

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from discord_helpers import GuildOnlyCog, listen_permission_error, require_guild, send_chunks, send_group_usage

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
        guild = require_guild(ctx)
        perms = vc.permissions_for(guild.me)
        if not (perms.connect and perms.speak):
            await ctx.send(f"⚠️ <#{vc.id}> に接続・発言する権限が Bot にありません。", ephemeral=True)
            return
        # テキストチャンネル未指定時は VC 内チャット（VC と同じ ID）を読み上げる
        text_id = text.id if text else vc.id
        # /listen add と同じく、実行者が閲覧できないチャンネルは読み上げ先にできない
        error = listen_permission_error(guild, text_id, ctx.author)
        if error:
            await ctx.send(error, ephemeral=True)
            return
        self.guild_settings.set_autojoin(guild.id, vc.id, text_id)
        await ctx.send(f"🔁 <#{vc.id}> に人が入ったら自動参加し、<#{text_id}> を読み上げます。")

    @autojoin_group.command(name="remove", description="自動参加 VC の登録を解除します")
    @app_commands.describe(vc="解除するボイスチャンネル")
    @commands.has_permissions(manage_guild=True)
    async def autojoin_remove_prefix(self, ctx: commands.Context, vc: discord.VoiceChannel):
        removed = self.guild_settings.remove_autojoin(require_guild(ctx).id, vc.id)
        msg = f"🛑 <#{vc.id}> の自動参加を解除しました。" if removed else f"<#{vc.id}> は自動参加に登録されていません。"
        await ctx.send(msg)

    @autojoin_group.command(name="list", description="自動参加 VC の一覧を表示します")
    @commands.has_permissions(manage_guild=True)
    async def autojoin_list_prefix(self, ctx: commands.Context):
        guild = require_guild(ctx)
        entries = self.guild_settings.autojoin_all(guild.id)
        # 削除済みの VC は /autojoin remove で指定できないため、ここで登録を解除する
        stale = [vc_id for vc_id in entries if guild.get_channel(vc_id) is None]
        for vc_id in stale:
            self.guild_settings.remove_autojoin(guild.id, vc_id)
            del entries[vc_id]
        if not entries:
            msg = "自動参加する VC は登録されていません。"
        else:
            lines = "\n".join(f"• <#{vc_id}> → <#{text_id}>" for vc_id, text_id in entries.items())
            msg = f"🔁 自動参加 VC（VC → 読み上げ先）:\n{lines}"
        if stale:
            msg += f"\n（削除済みの VC {len(stale)}件の登録を解除しました）"
        await send_chunks(ctx, msg)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        """削除された VC の自動参加登録を解除する"""
        self.guild_settings.remove_autojoin(channel.guild.id, channel.id)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        """サーバーから退出・キックされたら、そのサーバーの設定を削除する"""
        self.guild_settings.clear(guild.id)

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
        added = self.guild_settings.add_ignored(require_guild(ctx).id, user.id)
        msg = f"🔕 <@{user.id}> のメッセージを読み上げ対象外にしました。" if added else f"<@{user.id}> はすでに除外されています。"
        await ctx.send(msg, ephemeral=True)

    @ignore_group.command(name="remove", description="ユーザーの読み上げ除外を解除します（サーバー管理権限が必要）")
    @app_commands.describe(user="除外を解除するユーザー")
    @commands.has_permissions(manage_guild=True)
    # サーバーを退出したユーザーも解除できるよう、Member ではなく User で受ける
    async def ignore_remove_prefix(self, ctx: commands.Context, user: discord.User):
        removed = self.guild_settings.remove_ignored(require_guild(ctx).id, user.id)
        msg = f"🔔 <@{user.id}> の読み上げ除外を解除しました。" if removed else f"<@{user.id}> は除外されていません。"
        await ctx.send(msg, ephemeral=True)

    @ignore_group.command(name="list", description="読み上げ除外ユーザーの一覧を表示します（サーバー管理権限が必要）")
    @commands.has_permissions(manage_guild=True)
    async def ignore_list_prefix(self, ctx: commands.Context):
        ignored = self.guild_settings.ignored_all(require_guild(ctx).id)
        if not ignored:
            msg = "読み上げ除外ユーザーはいません。"
        else:
            lines = "\n".join(f"• <@{uid}>" for uid in sorted(ignored))
            msg = f"🔕 読み上げ除外ユーザー ({len(ignored)}人):\n{lines}"
        await send_chunks(ctx, msg, ephemeral=True)

    @ignore_group.command(name="me", description="自分のメッセージの読み上げ除外を切り替えます")
    async def ignore_me_prefix(self, ctx: commands.Context):
        if self.guild_settings.toggle_ignored(require_guild(ctx).id, ctx.author.id):
            msg = "🔕 あなたのメッセージを読み上げ対象外にしました。もう一度実行すると戻ります。"
        else:
            msg = "🔔 あなたのメッセージを再び読み上げます。"
        await ctx.send(msg, ephemeral=True)

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
