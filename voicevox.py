"""VOICEVOX ENGINE の非同期 HTTP クライアント"""

import asyncio
import json

import aiohttp


class VoicevoxError(Exception):
    pass


class VoicevoxClient:
    def __init__(
        self,
        base_url: str,
        max_retries: int = 2,
        retry_backoff: float = 0.5,
    ):
        self.base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(limit=20, ttl_dns_cache=300)
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        timeout: float,
        retry_on_timeout: bool = True,
        **kwargs,
    ) -> bytes:
        """VOICEVOX への HTTP リクエスト。

        LXC↔VM 間の瞬断や 5xx を吸収するため、接続エラー・サーバエラーは
        指数バックオフで最大 max_retries 回まで再試行する。タイムアウトは
        retry_on_timeout=False の呼び出し（長い synthesis 等）では再試行しない。
        失敗時は VoicevoxError を送出する。
        """
        session = await self._get_session()
        to = aiohttp.ClientTimeout(total=timeout)
        url = f"{self.base_url}{path}"
        last_exc: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                async with session.request(method, url, timeout=to, **kwargs) as resp:
                    if resp.status != 200:
                        # 5xx は一時的とみなして再試行、それ以外は即エラー
                        if resp.status >= 500 and attempt < self._max_retries:
                            last_exc = VoicevoxError(f"{path} failed: HTTP {resp.status}")
                            await asyncio.sleep(self._retry_backoff * (2 ** attempt))
                            continue
                        raise VoicevoxError(f"{path} failed: HTTP {resp.status}")
                    return await resp.read()
            except asyncio.TimeoutError as e:
                last_exc = e
                if retry_on_timeout and attempt < self._max_retries:
                    await asyncio.sleep(self._retry_backoff * (2 ** attempt))
                    continue
                raise VoicevoxError(f"VOICEVOX ENGINE がタイムアウトしました（{path}）") from e
            except aiohttp.ClientConnectionError as e:
                # ServerDisconnectedError 等もここで捕捉される
                last_exc = e
                if attempt < self._max_retries:
                    await asyncio.sleep(self._retry_backoff * (2 ** attempt))
                    continue
                raise VoicevoxError(
                    "VOICEVOX ENGINE に接続できません。起動しているか確認してください。"
                ) from e

        # 通常ここには到達しない（ループ内で return か raise する）
        raise VoicevoxError(f"VOICEVOX request failed: {last_exc}")

    async def synthesis(self, text: str, speaker: int, speed: float = 1.0) -> bytes:
        """テキストを音声合成して WAV の bytes を返す"""
        # Step 1: audio_query（短時間・タイムアウトも再試行）
        raw = await self._request(
            "POST",
            "/audio_query",
            params={"text": text, "speaker": speaker},
            timeout=10,
        )
        query = json.loads(raw)

        # 速度を上書き
        query["speedScale"] = speed

        # Step 2: synthesis（長時間。タイムアウトは再試行せずキュー詰まりを防ぐ）
        return await self._request(
            "POST",
            "/synthesis",
            params={"speaker": speaker},
            json=query,
            timeout=30,
            retry_on_timeout=False,
        )

    async def get_speakers(self) -> list[dict]:
        """利用可能なスピーカー一覧を返す"""
        raw = await self._request("GET", "/speakers", timeout=10)
        return json.loads(raw)
