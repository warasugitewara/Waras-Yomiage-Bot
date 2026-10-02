"""Cog 共通の Discord 送信ヘルパー"""

import discord
from discord.ext import commands


async def send_response(
    ctx_or_inter: commands.Context | discord.Interaction,
    msg: str,
    ephemeral: bool = False,
) -> None:
    """Context / Interaction 両対応の送信ヘルパー（ephemeral は Interaction のみ有効）"""
    if isinstance(ctx_or_inter, discord.Interaction):
        if ctx_or_inter.response.is_done():
            await ctx_or_inter.followup.send(msg, ephemeral=ephemeral)
        else:
            await ctx_or_inter.response.send_message(msg, ephemeral=ephemeral)
    else:
        await ctx_or_inter.send(msg)


async def send_group_usage(ctx: commands.Context) -> None:
    """サブコマンドなしでグループを実行したときに、使えるサブコマンドを案内する。

    help_command=None のため ctx.send_help() は何も送らない。
    """
    group = ctx.command
    if not isinstance(group, commands.Group):
        return
    subs = "|".join(sorted(c.name for c in group.commands))
    await ctx.send(f"使い方: `{ctx.prefix}{group.qualified_name} <{subs}>`（詳しくは `/help`）")
