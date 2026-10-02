"""Cog 共通の Discord 送信ヘルパー"""

import discord
from discord import app_commands
from discord.ext import commands

# Discord メッセージの安全な最大文字数
_DISCORD_MAX = 1900


def require_guild(ctx_or_inter: commands.Context | discord.Interaction) -> discord.Guild:
    """ギルド必須コマンド用。DM は cog_check / interaction_check で弾かれるため通常は到達しない"""
    guild = ctx_or_inter.guild
    if guild is None:
        raise commands.NoPrivateMessage()
    return guild


class GuildOnlyCog(commands.Cog):
    """サーバー内でのみ使えるコマンドをまとめる Cog の基底（DM での実行は案内を返して拒否する）"""

    async def cog_check(self, ctx: commands.Context) -> bool:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        return True

    async def interaction_check(self, interaction: discord.Interaction, /) -> bool:
        if interaction.guild is None:
            raise app_commands.NoPrivateMessage()
        return True


def voice_client_of(guild: discord.Guild) -> discord.VoiceClient | None:
    """guild.voice_client は VoiceProtocol 型のため VoiceClient に絞り込んで返す"""
    vc = guild.voice_client
    return vc if isinstance(vc, discord.VoiceClient) else None


async def send_response(
    ctx_or_inter: commands.Context | discord.Interaction,
    msg: str,
    ephemeral: bool = False,
) -> None:
    """Context / Interaction 両対応の送信ヘルパー（ephemeral は Interaction と hybrid のスラッシュ実行で有効）"""
    if isinstance(ctx_or_inter, discord.Interaction):
        if ctx_or_inter.response.is_done():
            await ctx_or_inter.followup.send(msg, ephemeral=ephemeral)
        else:
            await ctx_or_inter.response.send_message(msg, ephemeral=ephemeral)
    else:
        await ctx_or_inter.send(msg, ephemeral=ephemeral)


async def send_group_usage(ctx: commands.Context) -> None:
    """サブコマンドなしでグループを実行したときに、使えるサブコマンドを案内する。

    help_command=None のため ctx.send_help() は何も送らない。
    hybrid_group はサブコマンド実行時にもグループ本体が先に呼ばれるため、その場合は何もしない。
    """
    if ctx.invoked_subcommand is not None:
        return
    group = ctx.command
    if not isinstance(group, commands.Group):
        return
    subs = "|".join(sorted(c.name for c in group.commands))
    await ctx.send(f"使い方: `{ctx.prefix}{group.qualified_name} <{subs}>`（詳しくは `/help`）")


async def send_chunks(
    ctx_or_inter: commands.Context | discord.Interaction,
    text: str,
    ephemeral: bool = False,
) -> None:
    """長いテキストを _DISCORD_MAX 文字以内に分割して送信する"""
    chunks = [text[i:i + _DISCORD_MAX] for i in range(0, len(text), _DISCORD_MAX)]
    for i, chunk in enumerate(chunks):
        if i == 0:
            await send_response(ctx_or_inter, chunk, ephemeral=ephemeral)
        elif isinstance(ctx_or_inter, discord.Interaction):
            await ctx_or_inter.followup.send(chunk, ephemeral=ephemeral)
        else:
            await ctx_or_inter.send(chunk, ephemeral=ephemeral)
