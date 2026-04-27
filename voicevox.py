"""VOICEVOX ENGINE の非同期 HTTP クライアント"""

import io
import aiohttp


class VoicevoxError(Exception):
    pass


class VoicevoxClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def synthesis(self, text: str, speaker: int, speed: float = 1.0) -> io.BytesIO:
        """テキストを音声合成して WAV の BytesIO を返す"""
        session = await self._get_session()

        # Step 1: audio_query
        try:
            async with session.post(
                f"{self.base_url}/audio_query",
                params={"text": text, "speaker": speaker},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    raise VoicevoxError(f"audio_query failed: {resp.status}")
                query = await resp.json()
        except aiohttp.ClientConnectionError:
            raise VoicevoxError("VOICEVOX ENGINE に接続できません。起動しているか確認してください。")

        # 速度を上書き
        query["speedScale"] = speed

        # Step 2: synthesis
        async with session.post(
            f"{self.base_url}/synthesis",
            params={"speaker": speaker},
            json=query,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status != 200:
                raise VoicevoxError(f"synthesis failed: {resp.status}")
            wav_bytes = await resp.read()

        return io.BytesIO(wav_bytes)

    async def get_speakers(self) -> list[dict]:
        """利用可能なスピーカー一覧を返す"""
        session = await self._get_session()
        async with session.get(
            f"{self.base_url}/speakers",
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                raise VoicevoxError(f"speakers failed: {resp.status}")
            return await resp.json()
