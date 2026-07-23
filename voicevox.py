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
        max_retries: int | None = None,
        **kwargs,
    ) -> bytes:
        """VOICEVOX への HTTP リクエスト。

        LXC↔VM 間の瞬断や 5xx を吸収するため、接続エラー・サーバエラーは
        指数バックオフで最大 max_retries 回まで再試行する。タイムアウトは
        retry_on_timeout=False の呼び出し（長い synthesis 等）では再試行しない。
        max_retries を明示すればインスタンス既定値を上書きする（health 用の
        死活確認など、待たせたくない呼び出しで 0 を渡す）。
        失敗時は VoicevoxError を送出する。
        """
        retries = self._max_retries if max_retries is None else max_retries
        session = await self._get_session()
        to = aiohttp.ClientTimeout(total=timeout)
        url = f"{self.base_url}{path}"
        last_exc: Exception | None = None

        for attempt in range(retries + 1):
            try:
                async with session.request(method, url, timeout=to, **kwargs) as resp:
                    if resp.status != 200:
                        # 5xx は一時的とみなして再試行、それ以外は即エラー
                        if resp.status >= 500 and attempt < retries:
                            last_exc = VoicevoxError(f"{path} failed: HTTP {resp.status}")
                            await asyncio.sleep(self._retry_backoff * (2 ** attempt))
                            continue
                        raise VoicevoxError(f"{path} failed: HTTP {resp.status}")
                    return await resp.read()
            except asyncio.TimeoutError as e:
                last_exc = e
                if retry_on_timeout and attempt < retries:
                    await asyncio.sleep(self._retry_backoff * (2 ** attempt))
                    continue
                raise VoicevoxError(f"VOICEVOX ENGINE がタイムアウトしました（{path}）") from e
            except aiohttp.ClientError as e:
                # ClientConnectionError（ServerDisconnectedError 等）に加え、
                # 受信途中の ClientPayloadError 等もここで捕捉して再試行する
                last_exc = e
                if attempt < retries:
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
        try:
            query = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise VoicevoxError(f"VOICEVOX の応答が不正です（/audio_query）: {e}") from e

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
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise VoicevoxError(f"VOICEVOX の応答が不正です（/speakers）: {e}") from e

    async def version(self) -> str:
        """VOICEVOX ENGINE のバージョン文字列を返す（死活確認用）。

        health チェックから呼ばれるため、リトライせず短いタイムアウトで
        一度だけ確認する。不正応答は synthesis / get_speakers と同様に
        VoicevoxError にし、「読めたが内容が怪しい」状態を正常扱いにしない
        （リバースプロキシの 200 HTML などを緑表示にしないため）。
        """
        raw = await self._request("GET", "/version", timeout=3, max_retries=0)
        try:
            # /version は JSON 文字列（例: "0.14.0"）を返す
            return str(json.loads(raw))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise VoicevoxError(f"VOICEVOX の応答が不正です（/version）: {e}") from e
