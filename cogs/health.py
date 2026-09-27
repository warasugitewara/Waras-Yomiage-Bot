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

from version import VERSION


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
        "disk":     psutil.disk_usage("/").percent,
    }


async def _probe_voicevox(bot: commands.Bot) -> str | None:
    """TTS Cog の VoicevoxClient を借りて ENGINE の死活を確認する。
    成功: "✅ vX.Y.Z / 12 ms"、失敗: "❌ 接続不可"。TTS 未ロード時は None。
    """
    tts = bot.get_cog("TTS")
    client = getattr(tts, "voicevox", None)
    if client is None:
        return None
    t0 = time.perf_counter()
    try:
        version = await client.version()
    except Exception:
        return "❌ 接続不可"
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return f"✅ `v{version}` / `{elapsed_ms:.0f} ms`"


class Health(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="health", description="Botのシステム状態を表示します")
    async def health(self, ctx: commands.Context):
        """Bot のバージョン・応答速度・サーバー数・メモリ・CPU・ネットワークを表示します。"""
        # ホストのリソース情報を含むためオーナー限定（OWNER_IDS 未設定時は誰も使えない）
        owner_ids: frozenset[int] = getattr(self.bot, "owner_ids", frozenset())
        if ctx.author.id not in owner_ids:
            await ctx.send("⛔ このコマンドはオーナーのみ使用できます。", ephemeral=True)
            return

        await ctx.defer(ephemeral=True)

        t0 = time.perf_counter()
        metrics = await _collect_metrics()
        voicevox_status = await _probe_voicevox(self.bot)
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
                f"**バージョン** `v{VERSION}`\n"
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
                f"**CPU** `{metrics['cpu']:.1f}%`\n"
                f"**Disk** `{metrics['disk']:.1f}%`"
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
        if voicevox_status is not None:
            embed.add_field(
                name="🎤 VOICEVOX ENGINE",
                value=voicevox_status,
                inline=True,
            )
        embed.set_footer(text=f"計測時間: {elapsed_ms:.0f} ms")

        await ctx.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Health(bot))
