"""Waras-Yomiage-Bot — VOICEVOX を使った Discord 読み上げBot"""

import asyncio
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

PREFIX = os.getenv("PREFIX", "!")


class YomiageBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            command_prefix=PREFIX,
            intents=intents,
            help_command=None,  # カスタム help コマンドを使用
        )

    async def setup_hook(self):
        await self.load_extension("cogs.tts")
        await self.load_extension("cogs.utility")

        # GUILD_ID が設定されている場合はギルド限定sync（即時反映）、未設定の場合はグローバルsync
        guild_id_str = os.getenv("GUILD_ID", "")
        if guild_id_str.isdigit():
            guild = discord.Object(id=int(guild_id_str))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"[Bot] スラッシュコマンドをギルド {guild_id_str} に同期しました（即時反映）。")
        else:
            await self.tree.sync()
            print("[Bot] スラッシュコマンドをグローバル同期しました（反映まで最大1時間）。")

    async def on_ready(self):
        print(f"[Bot] ログイン: {self.user} (ID: {self.user.id})")
        print(f"[Bot] プレフィックス: {PREFIX}")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name=f"{PREFIX}join | /join",
            )
        )


async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise ValueError(".env に DISCORD_TOKEN が設定されていません。")

    bot = YomiageBot()
    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
