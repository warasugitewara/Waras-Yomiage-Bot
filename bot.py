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
            help_command=commands.DefaultHelpCommand(),
        )

    async def setup_hook(self):
        await self.load_extension("cogs.tts")
        # スラッシュコマンドをグローバル同期
        await self.tree.sync()
        print("[Bot] スラッシュコマンドを同期しました。")

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
