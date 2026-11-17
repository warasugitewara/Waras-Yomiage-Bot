"""主 ENGINE（GPU）で合成できないときのフォールバック"""

import asyncio
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

import tts_pipeline
from tts_pipeline import SpeechSynthesizer, TTSItem
from voicevox import VoicevoxClient, VoicevoxEngineError, VoicevoxError


class _FakeEngine:
    """synthesis だけを持つ VoicevoxClient の代用品。fail に入れた声は指定の例外で失敗する"""

    def __init__(self, name: str, fail: dict[int, type[VoicevoxError]] | None = None) -> None:
        self.name = name
        self.fail = fail or {}
        self.calls: list[int] = []

    async def synthesis(self, text: str, speaker: int, speed: float = 1.0) -> bytes:
        self.calls.append(speaker)
        exc = self.fail.get(speaker)
        if exc is not None:
            raise exc(f"{self.name} speaker={speaker} failed")
        return f"{self.name}:{speaker}".encode()

    async def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _fake_pcm(monkeypatch: pytest.MonkeyPatch):
    async def fake_pcm(wav: bytes) -> bytes:
        return wav

    monkeypatch.setattr(tts_pipeline, "wav_to_pcm", fake_pcm)


def _make(
    primary: _FakeEngine, fallback: _FakeEngine | None, default_speaker: int = 3
) -> tuple[SpeechSynthesizer, list[str]]:
    notified: list[str] = []

    async def notify(title: str, description: str) -> None:
        notified.append(title)

    synth = SpeechSynthesizer(
        primary,
        fallback=fallback,
        default_speaker=default_speaker,
        notify=notify,
    )
    return synth, notified


async def test_primary_success_does_not_touch_fallback() -> None:
    primary, fallback = _FakeEngine("gpu"), _FakeEngine("cpu")
    synth, notified = _make(primary, fallback)

    pcm = await synth.synthesize(TTSItem("a", 36, 1.0))

    assert pcm == b"gpu:36"
    assert fallback.calls == []
    assert notified == []


async def test_engine_error_falls_back_to_cpu_and_avoids_primary() -> None:
    """GPU で 5xx になった声は CPU で読み、以後しばらく GPU に送らない"""
    primary = _FakeEngine("gpu", fail={36: VoicevoxEngineError})
    fallback = _FakeEngine("cpu")
    synth, notified = _make(primary, fallback)

    assert await synth.synthesize(TTSItem("a", 36, 1.0)) == b"cpu:36"
    assert await synth.synthesize(TTSItem("b", 36, 1.0)) == b"cpu:36"

    assert primary.calls == [36]  # 2 回目は GPU を飛ばす
    assert fallback.calls == [36, 36]
    assert ("a", 36, 1.0) in synth.cache  # 指定の声なのでキャッシュする
    assert notified == ["VOICEVOX 主 ENGINE で合成失敗"]


async def test_primary_is_retried_after_avoid_period(monkeypatch: pytest.MonkeyPatch) -> None:
    primary = _FakeEngine("gpu", fail={36: VoicevoxEngineError})
    fallback = _FakeEngine("cpu")
    synth, _ = _make(primary, fallback)
    now = [1000.0]
    monkeypatch.setattr(tts_pipeline.time, "monotonic", lambda: now[0])

    await synth.synthesize(TTSItem("a", 36, 1.0))
    primary.fail.clear()  # GPU の VRAM が空いた
    now[0] += tts_pipeline.PRIMARY_AVOID_SECONDS

    assert await synth.synthesize(TTSItem("b", 36, 1.0)) == b"gpu:36"
    assert primary.calls == [36, 36]


async def test_default_voice_when_all_engines_fail() -> None:
    """GPU も CPU も失敗したら、既定の声で読む。その音声はキャッシュしない"""
    primary = _FakeEngine("gpu", fail={36: VoicevoxEngineError})
    fallback = _FakeEngine("cpu", fail={36: VoicevoxError})
    synth, notified = _make(primary, fallback)

    pcm = await synth.synthesize(TTSItem("a", 36, 1.0))

    assert pcm == b"gpu:3"
    assert ("a", 36, 1.0) not in synth.cache
    assert notified == ["VOICEVOX 主 ENGINE で合成失敗", "VOICEVOX 既定の声で代替"]


async def test_default_voice_without_fallback_engine() -> None:
    """予備 ENGINE が未設定でも、主 ENGINE の既定の声で読む（声を避ける記録は残さない）"""
    primary = _FakeEngine("gpu", fail={36: VoicevoxEngineError})
    synth, _ = _make(primary, None)

    assert await synth.synthesize(TTSItem("a", 36, 1.0)) == b"gpu:3"
    assert await synth.synthesize(TTSItem("b", 36, 1.0)) == b"gpu:3"
    assert primary.calls == [36, 3, 36, 3]


async def test_primary_down_uses_cpu_but_not_default_voice_on_primary() -> None:
    """GPU に接続できないときは CPU で読む。CPU も失敗したら、GPU への既定の声の再送はしない"""
    primary = _FakeEngine("gpu", fail={36: VoicevoxError, 37: VoicevoxError, 3: VoicevoxError})
    fallback = _FakeEngine("cpu")
    synth, _ = _make(primary, fallback)
    assert await synth.synthesize(TTSItem("a", 36, 1.0)) == b"cpu:36"

    fallback.fail[37] = VoicevoxError
    with pytest.raises(VoicevoxError):
        await synth.synthesize(TTSItem("b", 37, 1.0))
    assert 3 not in primary.calls
    # 接続エラーは声のせいではないので、次も GPU を先に試す
    assert not synth._primary_avoided(36)


async def test_default_speaker_failure_raises() -> None:
    primary = _FakeEngine("gpu", fail={3: VoicevoxEngineError})
    fallback = _FakeEngine("cpu", fail={3: VoicevoxError})
    synth, _ = _make(primary, fallback)

    with pytest.raises(VoicevoxError):
        await synth.synthesize(TTSItem("a", 3, 1.0))
    assert primary.calls == [3]  # 既定の声そのものは再送しない


# --------------------------------------------------------------------------- #
# VoicevoxClient: 合成の 5xx は再試行しない
# --------------------------------------------------------------------------- #


async def _serve(handler) -> TestServer:
    app = web.Application()
    app.router.add_post("/audio_query", handler)
    app.router.add_post("/synthesis", handler)
    server = TestServer(app)
    await server.start_server()
    return server


async def test_synthesis_does_not_retry_engine_error() -> None:
    hits = 0

    async def handler(request: web.Request) -> web.Response:
        nonlocal hits
        hits += 1
        return web.Response(status=500, text="推論に失敗しました")

    server = await _serve(handler)
    client = VoicevoxClient(str(server.make_url("")), retry_backoff=0)
    try:
        with pytest.raises(VoicevoxEngineError):
            await client.synthesis("a", 36)
        assert hits == 1
    finally:
        await client.close()
        await server.close()


async def test_synthesis_still_retries_connection_error() -> None:
    """接続できないときは従来どおり再試行し、VoicevoxEngineError ではないエラーにする"""
    async def handler(request: web.Request) -> web.Response:
        return web.Response()

    server = await _serve(handler)
    url = str(server.make_url(""))
    await server.close()  # 誰も待ち受けていないポート
    client = VoicevoxClient(url, retry_backoff=0)
    try:
        with pytest.raises(VoicevoxError) as info:
            await client.synthesis("a", 3)
        assert not isinstance(info.value, VoicevoxEngineError)
    finally:
        await client.close()


async def test_synthesis_success_roundtrip() -> None:
    async def handler(request: web.Request) -> web.Response:
        if request.path == "/audio_query":
            return web.json_response({"speedScale": 1.0})
        body = await request.json()
        return web.Response(body=json.dumps(body).encode())

    server = await _serve(handler)
    client = VoicevoxClient(str(server.make_url("")))
    try:
        wav = await asyncio.wait_for(client.synthesis("a", 3, speed=1.2), timeout=5)
        assert json.loads(wav)["speedScale"] == 1.2
    finally:
        await client.close()
        await server.close()
