"""health Cog — システム状態確認コマンド（HEALTH_ENABLED=true のときのみロード）"""

import asyncio
import os
import platform
import sys
import time

import discord
import psutil
from discord import app_commands
from discord.ext import commands

_VERSION = "1.0.0"


def _fmt_bytes(n: float) -> str:
    """バイト数を人間が読みやすい形式に変換"""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


async def _collect_metrics() -> dict:
    """CPU・メモリ・ネットワークを計測して返す（0.5s サンプリング）"""
    loop = asyncio.get_running_loop()
    proc = psutil.Process()
    mem_bytes = proc.memory_info().rss

    net1 = psutil.net_io_counters()

    # CPU は 0.5 秒間ブロックして計測（executor でイベントループをブロックしない）
    cpu_pct = await loop.run_in_executor(None, lambda: psutil.cpu_percent(interval=0.5))

    net2 = psutil.net_io_counters()
    # 0.5 秒間の差分 × 2 = 1 秒あたりのレート
    upload   = (net2.bytes_sent - net1.bytes_sent) * 2
    download = (net2.bytes_recv - net1.bytes_recv) * 2

    return {
        "mem":      mem_bytes,
        "cpu":      cpu_pct,
        "upload":   upload,
        "download": download,
    }


class Health(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="health", description="Botのシステム状態を表示します")
    async def health(self, ctx: commands.Context):
        """Bot のバージョン・応答速度・サーバー数・メモリ・CPU・ネットワークを表示します。"""
        await ctx.defer()

        t0 = time.perf_counter()
        metrics = await _collect_metrics()
        elapsed_ms = (time.perf_counter() - t0) * 1000

        prefix = os.getenv("PREFIX", "!")
        server_count = len(self.bot.guilds)
        user_count   = sum(g.member_count or 0 for g in self.bot.guilds)
        ws_ping_ms   = round(self.bot.latency * 1000)
        py_ver       = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

        embed = discord.Embed(
            title="🩺 Health Check",
            color=discord.Color.green(),
        )
        embed.add_field(
            name="🤖 Bot",
            value=(
                f"**バージョン** `v{_VERSION}`\n"
                f"**Prefix** `{prefix}` | `/`\n"
                f"**discord.py** `{discord.__version__}`"
            ),
            inline=True,
        )
        embed.add_field(
            name="🌐 接続",
            value=(
                f"**WS Ping** `{ws_ping_ms} ms`\n"
                f"**サーバー** `{server_count}`\n"
                f"**ユーザー** `{user_count:,}`"
            ),
            inline=True,
        )
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # 改行用の空フィールド
        embed.add_field(
            name="💻 システム",
            value=(
                f"**Python** `{py_ver}`\n"
                f"**OS** `{platform.system()} {platform.release()}`"
            ),
            inline=True,
        )
        embed.add_field(
            name="⚙️ リソース",
            value=(
                f"**メモリ** `{_fmt_bytes(metrics['mem'])}`\n"
                f"**CPU** `{metrics['cpu']:.1f}%`"
            ),
            inline=True,
        )
        embed.add_field(
            name="📡 ネットワーク（/s）",
            value=(
                f"**📤 上り** `{_fmt_bytes(metrics['upload'])}`\n"
                f"**📥 下り** `{_fmt_bytes(metrics['download'])}`"
            ),
            inline=True,
        )
        embed.set_footer(text=f"計測時間: {elapsed_ms:.0f} ms")

        await ctx.reply(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Health(bot))
