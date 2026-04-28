"""Discord Webhook にエラー/警告/情報通知を送信するオプション機能。

ERROR_WEBHOOK_URL が .env に設定されていない場合はすべて無効（何もしない）。
"""

import os
import time
import traceback
from typing import Any

import aiohttp
import discord

_COLORS = {
    "error":   0xED4245,  # Discord red
    "warning": 0xFEE75C,  # Discord yellow
    "info":    0x57F287,  # Discord green
}

_ICONS = {
    "error":   "🔴",
    "warning": "🟡",
    "info":    "🟢",
}


class WebhookLogger:
    """Discord Webhook にエラー/警告/情報を送信するロガー。

    同一 (level, title) の通知は 30 秒以内に何度来ても 1 回だけ送信する。
    クールダウンは送信成功時のみ更新するため、失敗・タイムアウト後は即再試行できる。
    """

    def __init__(self):
        # WebhookLogger() は load_dotenv() 呼び出し後に生成すること
        self.url: str | None = os.getenv("ERROR_WEBHOOK_URL") or None
        self._session: aiohttp.ClientSession | None = None
        # (level, title) → 最終送信成功 monotonic 時刻
        self._cooldowns: dict[tuple[str, str], float] = {}
        self._cooldown_secs = 30.0

    @property
    def enabled(self) -> bool:
        return self.url is not None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _is_cooling_down(self, level: str, title: str) -> bool:
        return time.monotonic() - self._cooldowns.get((level, title), 0.0) < self._cooldown_secs

    def _mark_sent(self, level: str, title: str) -> None:
        self._cooldowns[(level, title)] = time.monotonic()

    async def send(
        self,
        level: str,
        title: str,
        description: str = "",
        exc: BaseException | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Webhook に通知を送信する。URL 未設定・クールダウン中はスキップ。"""
        if not self.enabled or self._is_cooling_down(level, title):
            return

        icon = _ICONS.get(level, "⚪")
        embed: dict[str, Any] = {
            "title": f"{icon} {title}",
            "color": _COLORS.get(level, _COLORS["error"]),
            "timestamp": discord.utils.utcnow().isoformat(),
            "fields": [],
        }

        if description:
            embed["description"] = description[:2000]

        if exc:
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            embed["fields"].append({
                "name": "📋 トレースバック",
                "value": f"```\n{tb[-1000:]}\n```",
                "inline": False,
            })

        if context:
            embed["fields"].append({
                "name": "🔍 コンテキスト",
                "value": "\n".join(f"**{k}**: {v}" for k, v in context.items())[:1024],
                "inline": False,
            })

        try:
            session = await self._get_session()
            async with session.post(
                self.url,
                json={"embeds": [embed]},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status in (200, 204):
                    self._mark_sent(level, title)
                else:
                    print(f"[WEBHOOK] 送信失敗: HTTP {resp.status}")
        except Exception as e:
            print(f"[WEBHOOK] 送信エラー: {e}")
