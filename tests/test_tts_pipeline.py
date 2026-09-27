import asyncio
from types import SimpleNamespace
from typing import cast

import pytest
from discord.ext import commands

import cogs.tts as tts_mod
from cogs.tts import TTS, TTSItem


class _FakeWebhook:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, level: str, title: str, *args: object, **kwargs: object) -> None:
        self.sent.append((level, title))


def _make_cog() -> TTS:
    guild = SimpleNamespace(voice_client=object())
    bot = SimpleNamespace(
        user_voice_store=SimpleNamespace(get=lambda _uid: 3),
        get_guild=lambda _gid: guild,
        webhook=_FakeWebhook(),
    )
    return TTS(cast(commands.Bot, bot))


@pytest.fixture
def cog(monkeypatch: pytest.MonkeyPatch):
    async def fake_pcm(wav: bytes) -> bytes:
        return b"pcm:" + wav

    monkeypatch.setattr(tts_mod, "_wav_to_pcm", fake_pcm)
    c = _make_cog()
    yield c


async def test_cancelling_one_guild_does_not_hang_other_guild(cog: TTS, monkeypatch: pytest.MonkeyPatch) -> None:
    """同一テキストを2ギルドで合成中、所有側ワーカーのキャンセルで他方が停止しないこと"""
    release = asyncio.Event()

    async def fake_synthesis(text: str, speaker: int, speed: float) -> bytes:
        await release.wait()
        return b"wav"

    monkeypatch.setattr(cog.voicevox, "synthesis", fake_synthesis)
    item = TTSItem(text="こんにちは", speaker_id=3, speed=1.0)
    cog._get_queue(1).put_nowait(item)
    cog._get_queue(2).put_nowait(item)

    w1 = asyncio.create_task(cog._synthesizer(1))
    await asyncio.sleep(0.01)  # ギルド1が合成を開始
    w2 = asyncio.create_task(cog._synthesizer(2))
    await asyncio.sleep(0.01)  # ギルド2が同一キーの合成待ちに入る

    w1.cancel()  # /leave 相当
    await asyncio.gather(w1, return_exceptions=True)
    release.set()

    try:
        pcm = await asyncio.wait_for(cog._get_pcm_queue(2).get(), timeout=1.0)
        assert pcm == b"pcm:wav"
        await asyncio.sleep(0)
        assert not cog._in_flight
    finally:
        w2.cancel()
        await asyncio.gather(w2, return_exceptions=True)
        await cog.cog_unload()


async def test_synthesis_failure_is_reported_to_all_waiters(cog: TTS, monkeypatch: pytest.MonkeyPatch) -> None:
    """共有合成が失敗しても待機側がハングせず、次のメッセージを処理できること"""
    calls = 0

    async def fake_synthesis(text: str, speaker: int, speed: float) -> bytes:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        if text == "失敗":
            raise tts_mod.VoicevoxError("boom")
        return b"ok"

    monkeypatch.setattr(cog.voicevox, "synthesis", fake_synthesis)
    for gid in (1, 2):
        cog._get_queue(gid).put_nowait(TTSItem(text="失敗", speaker_id=3, speed=1.0))
        cog._get_queue(gid).put_nowait(TTSItem(text="成功", speaker_id=3, speed=1.0))

    workers = [asyncio.create_task(cog._synthesizer(gid)) for gid in (1, 2)]
    try:
        for gid in (1, 2):
            pcm = await asyncio.wait_for(cog._get_pcm_queue(gid).get(), timeout=1.0)
            assert pcm == b"pcm:ok"
        assert calls == 2  # 同一キーは共有され、各テキスト1回ずつ合成
    finally:
        for w in workers:
            w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        await cog.cog_unload()


async def test_unload_cancels_shared_synthesis(cog: TTS, monkeypatch: pytest.MonkeyPatch) -> None:
    started = asyncio.Event()

    async def fake_synthesis(text: str, speaker: int, speed: float) -> bytes:
        started.set()
        await asyncio.sleep(3600)
        return b""

    monkeypatch.setattr(cog.voicevox, "synthesis", fake_synthesis)
    cog._get_queue(1).put_nowait(TTSItem(text="長文", speaker_id=3, speed=1.0))
    cog._ensure_worker(1)
    await asyncio.wait_for(started.wait(), timeout=1.0)

    await asyncio.wait_for(cog.cog_unload(), timeout=1.0)
    assert not cog._in_flight


async def test_dropping_oldest_keeps_unfinished_count(cog: TTS, monkeypatch: pytest.MonkeyPatch) -> None:
    """満杯時に最古を捨てても未完了カウンタがずれず join が完了すること"""
    monkeypatch.setattr(cog, "_ensure_worker", lambda _gid: None)
    q = cog._get_queue(1)
    for i in range(q.maxsize + 1):
        cog._enqueue_item(1, TTSItem(text=str(i), speaker_id=3, speed=1.0))

    assert q.qsize() == q.maxsize
    assert q.get_nowait().text == "1"  # 最古の "0" が捨てられている
    q.task_done()
    while not q.empty():
        q.get_nowait()
        q.task_done()
    await asyncio.wait_for(q.join(), timeout=1.0)
