import os
import asyncio
import aiohttp

async def kuma_heartbeat():
    push_url = os.getenv("UPTIME_KUMA_PUSH_URL")
    if not push_url:
        print("[KUMA] UPTIME_KUMA_PUSH_URL が未設定のためハートビートを無効化")
        return

    print(f"[KUMA] ハートビート開始")
    timeout = aiohttp.ClientTimeout(total=10)
    while True:
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    push_url,
                    params={
                        "status": "up",
                        "msg": "running"
                    }
                ):
                    pass

        except Exception as e:
            print(f"[KUMA] heartbeat failed: {type(e).__name__}")

        await asyncio.sleep(60)
