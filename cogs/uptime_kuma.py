import os
import asyncio
import aiohttp

async def kuma_heartbeat():
    push_url = os.getenv("UPTIME_KUMA_PUSH_URL")
    if not push_url:
        print("[KUMA] UPTIME_KUMA_PUSH_URL が未設定のためハートビートを無効化")
        return

    print("[KUMA] ハートビート開始")
    timeout = aiohttp.ClientTimeout(total=10)
    # セッションは使い回す（毎回生成すると接続プールが再利用されない）
    async with aiohttp.ClientSession(timeout=timeout) as session:
        while True:
            try:
                async with session.get(push_url) as resp:
                    # Push URL はトークンを含むためログに出さない
                    if resp.status != 200:
                        print(f"[KUMA] heartbeat failed: HTTP {resp.status}")

            except Exception as e:
                print(f"[KUMA] heartbeat failed: {type(e).__name__}")

            await asyncio.sleep(60)
