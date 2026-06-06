import os
import asyncio
import aiohttp

PUSH_URL = os.getenv("UPTIME_KUMA_PUSH_URL")

async def kuma_heartbeat():
    if not PUSH_URL:
        return

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    PUSH_URL,
                    params={
                        "status": "up",
                        "msg": "running"
                    }
                ):
                    pass

        except Exception as e:
            print(f"[KUMA] {e}")

        await asyncio.sleep(60)
