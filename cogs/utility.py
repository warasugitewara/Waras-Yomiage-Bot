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
    ("**── 管理者向け ──**",     ""),
    ("`/reload_speakers`",         "スピーカーキャッシュ更新（管理者のみ）"),
    ("**── オーナー向け ──**",   ""),
    ("`/owner export_users`",      "全ユーザーのボイス設定をJSONでエクスポート（オーナーのみ）"),
    ("`/owner import_users`",      "JSONからユーザーのボイス設定をインポート（オーナーのみ）"),
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

    @commands.hybrid_command(name="about", aliases=["status"], description="ボット情報を表示します")
    async def about(self, ctx: commands.Context):
        await ctx.defer()
        prefix = os.getenv("PREFIX", "!")
        voicevox_url = os.getenv("VOICEVOX_URL", "http://localhost:50021")
        default_speaker = os.getenv("DEFAULT_SPEAKER", "3")
        default_speed = os.getenv("DEFAULT_SPEED", "1.0")
        max_length = os.getenv("MAX_TEXT_LENGTH", "100")

        # ランタイム情報
        import platform, sys
        guild_count = len(self.bot.guilds)
        user_count = sum(g.member_count or 0 for g in self.bot.guilds)
        ws_ms = round(self.bot.latency * 1000)

        embed = discord.Embed(
            title="🔊 Waras-Yomiage-Bot",
            description=(
                "VOICEVOX を使ったローカル完結型 Discord 読み上げBot。\n"
                "外部サービス不要・低遅延・パイプライン処理で快適な読み上げを実現。"
            ),
            color=discord.Color.green(),
            url=_REPO_URL,
        )

        embed.add_field(name="🏷️ バージョン",    value=_VERSION,                       inline=True)
        embed.add_field(name="⌨️ プレフィックス", value=f"`{prefix}`",                  inline=True)
        embed.add_field(name="📡 WebSocket",     value=f"`{ws_ms} ms`",                inline=True)

        embed.add_field(name="🏠 サーバー数",    value=f"`{guild_count}`",              inline=True)
        embed.add_field(name="👥 ユーザー数",    value=f"`{user_count}`",               inline=True)
        embed.add_field(name="🐍 Python",        value=f"`{sys.version.split()[0]}`",  inline=True)

        embed.add_field(
            name="🎤 VOICEVOX ENGINE",
            value=(
                f"URL: `{voicevox_url}`\n"
                f"デフォルトスピーカーID: `{default_speaker}`\n"
                f"デフォルト速度: `{default_speed}x`\n"
                f"最大読み上げ文字数: `{max_length}文字`"
            ),
            inline=False,
        )

        embed.add_field(
            name="✨ 主な機能",
            value=(
                "• ユーザーごとのボイス設定（40+ キャラクター対応）\n"
                "• 複数テキストチャンネル同時読み上げ\n"
                "• 入退室アナウンス\n"
                "• 読み替え辞書\n"
                "• パイプライン合成（次メッセージを先読み）\n"
                "• prefix & slash コマンド両対応"
            ),
            inline=False,
        )

        embed.add_field(
            name="🔗 リンク",
            value=f"[ソースコード (GitHub)]({_REPO_URL})",
            inline=False,
        )

        # オーナー情報（OWNER_IDS が設定されている場合のみ表示）
        if self.bot.owner_ids:
            owner_lines = []
            for uid in sorted(self.bot.owner_ids):
                user = self.bot.get_user(uid)
                if user is None:
                    try:
                        user = await self.bot.fetch_user(uid)
                    except discord.NotFound:
                        pass
                label = f"{user.name} [{uid}]" if user else f"[{uid}]"
                owner_lines.append(label)
            embed.add_field(
                name="👑 オーナー",
                value="\n".join(owner_lines),
                inline=False,
            )

        embed.set_footer(text=f"discord.py {discord.__version__} • {platform.system()} • コンセプト: 簡単・低遅延・直感的・エコ")
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
