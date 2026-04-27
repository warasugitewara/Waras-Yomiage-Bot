"""utility Cog — ping / about / help"""

import os
import time

import discord
from discord import app_commands
from discord.ext import commands

_VERSION = "1.0.0"
_REPO_URL = "https://github.com/warasugitewara/Waras-Yomiage-Bot"

# コマンド一覧テキスト（help 用）
_COMMANDS = [
    ("`/join` `!join`",           "VC に参加して読み上げ開始"),
    ("`/leave` `!leave`",         "VC から退出"),
    ("`/skip` `!skip`",           "現在の読み上げをスキップ"),
    ("`/speed [倍率]` `!speed`",  "読み上げ速度を変更 (0.5–2.0)"),
    ("**── ボイス設定 ──**",       ""),
    ("`/myvoice list`",            "利用可能なスピーカー一覧を表示"),
    ("`/myvoice set <id>`",        "自分のボイスを設定"),
    ("`/myvoice reset`",           "ボイスをデフォルトに戻す"),
    ("`/myvoice info`",            "現在のボイス設定を確認"),
    ("`/voice <id>`",              "myvoice set のエイリアス"),
    ("**── チャンネル管理 ──**",   ""),
    ("`/listen add [ch]`",         "読み上げ対象チャンネルを追加"),
    ("`/listen remove [ch]`",      "読み上げ対象チャンネルを削除"),
    ("`/listen list`",             "読み上げ対象チャンネル一覧"),
    ("**── 辞書 ──**",             ""),
    ("`/dict add <word> <読み>`",  "読み替え辞書に追加"),
    ("`/dict remove <word>`",      "辞書から削除"),
    ("`/dict list`",               "辞書の一覧表示"),
    ("**── ユーティリティ ──**",   ""),
    ("`/ping`",                    "ボットの応答速度を確認"),
    ("`/about`",                   "ボット情報を表示"),
    ("`/help`",                    "このヘルプを表示"),
]


class Utility(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── ping ──────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="ping", description="ボットの応答速度を確認します")
    async def ping(self, ctx: commands.Context):
        t0 = time.perf_counter()
        await ctx.defer()
        elapsed = (time.perf_counter() - t0) * 1000
        ws_ms = round(self.bot.latency * 1000)
        await ctx.send(
            f"🏓 **Pong!**\n"
            f"WebSocket: `{ws_ms} ms`\n"
            f"応答時間: `{elapsed:.1f} ms`"
        )

    # ── about ─────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="about", description="ボット情報を表示します")
    async def about(self, ctx: commands.Context):
        await ctx.defer()
        prefix = os.getenv("PREFIX", "!")
        embed = discord.Embed(
            title="🔊 Waras-Yomiage-Bot",
            description="VOICEVOX を使ったローカル動作の Discord 読み上げBot",
            color=discord.Color.green(),
            url=_REPO_URL,
        )
        embed.add_field(name="バージョン", value=_VERSION, inline=True)
        embed.add_field(name="プレフィックス", value=f"`{prefix}`", inline=True)
        embed.add_field(name="エンジン", value="VOICEVOX ENGINE (ローカル)", inline=True)
        embed.add_field(name="ソースコード", value=f"[GitHub]({_REPO_URL})", inline=False)
        embed.set_footer(text="コンセプト: 簡単・低遅延・直感的")
        await ctx.send(embed=embed)

    # ── help ──────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="help", description="コマンド一覧を表示します")
    @app_commands.describe(command="詳細を見たいコマンド名（省略可）")
    async def help(self, ctx: commands.Context, command: str | None = None):
        await ctx.defer(ephemeral=True)

        if command:
            cmd = self.bot.get_command(command)
            if cmd is None:
                await ctx.send(f"⚠️ `{command}` というコマンドは見つかりません。", ephemeral=True)
                return
            embed = discord.Embed(
                title=f"/{cmd.name}",
                description=cmd.description or cmd.help or "説明なし",
                color=discord.Color.blurple(),
            )
            if cmd.aliases:
                embed.add_field(name="エイリアス", value=", ".join(cmd.aliases))
            if hasattr(cmd, "clean_params") and cmd.clean_params:
                params = " ".join(f"<{p}>" for p in cmd.clean_params)
                embed.add_field(name="引数", value=f"`{params}`")
            await ctx.send(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title="📖 コマンド一覧",
            description=f"スラッシュ `/` またはプレフィックス `{os.getenv('PREFIX', '!')}` で使えます。",
            color=discord.Color.blurple(),
        )
        for name, desc in _COMMANDS:
            embed.add_field(name=name, value=desc or "\u200b", inline=False)
        embed.set_footer(text="/help <コマンド名> で詳細表示")
        await ctx.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Utility(bot))
