import os
import asyncio
import aiohttp

PUSH_URL = os.getenv("UPTIME_KUMA_PUSH_URL")

async def kuma_heartbeat():
    if not PUSH_URL:
        return

    timeout = aiohttp.ClientTimeout(total=10)
    while True:
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    PUSH_URL,
                    params={
                        "status": "up",
                        "msg": "running"
                    }
                ):
                    pass

        except Exception as e:
            print(f"[KUMA] heartbeat failed: {type(e).__name__}")

        await asyncio.sleep(60)
