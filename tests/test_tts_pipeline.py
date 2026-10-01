import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import discord
import pytest
from discord.ext import commands

import cogs.tts as tts_mod
from cogs.tts import TTS, TTSItem
from guild_settings import GuildSettingsStore

if TYPE_CHECKING:
    from bot import YomiageBot


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
        command_prefix="!",
    )
    return TTS(cast("YomiageBot", bot))


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


def test_pcm_cache_is_bounded_by_bytes(cog: TTS, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tts_mod, "_PCM_CACHE_MAX_BYTES", 10)
    cog._cache_put(("a",), b"1234")
    cog._cache_put(("b",), b"1234")
    cog._cache_put(("c",), b"1234")  # 合計 12 > 10 で最古の a を破棄
    assert list(cog._pcm_cache) == [("b",), ("c",)]
    assert cog._pcm_cache_bytes == 8

    cog._cache_put(("b",), b"12")  # 上書き時は旧サイズを差し引く
    assert cog._pcm_cache_bytes == 6
    assert list(cog._pcm_cache) == [("c",), ("b",)]

    cog._cache_put(("big",), b"x" * 11)  # 単体で上限超過はキャッシュしない
    assert ("big",) not in cog._pcm_cache
    assert cog._pcm_cache_bytes == 6


async def test_synthesis_concurrency_is_limited(cog: TTS, monkeypatch: pytest.MonkeyPatch) -> None:
    running = 0
    peak = 0

    async def fake_synthesis(text: str, speaker: int, speed: float) -> bytes:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return b"wav"

    monkeypatch.setattr(cog.voicevox, "synthesis", fake_synthesis)
    tasks = [
        cog._get_or_start_synthesis((str(i), 3, 1.0), TTSItem(text=str(i), speaker_id=3, speed=1.0))
        for i in range(6)
    ]
    await asyncio.wait_for(asyncio.gather(*tasks), timeout=1.0)
    assert peak == tts_mod._SYNTH_CONCURRENCY
    await cog.cog_unload()


class _FakeChannelStore:
    def __init__(self, watched: set[int] | None = None) -> None:
        self.added: list[tuple[int, int]] = []
        self.watched = watched or set()

    def add(self, guild_id: int, channel_id: int) -> bool:
        self.added.append((guild_id, channel_id))
        return True

    def is_watched(self, guild_id: int, channel_id: int) -> bool:
        return channel_id in self.watched


def _voice_event(
    guild_id: int, before: object, after: object
) -> tuple[discord.Member, discord.VoiceState, discord.VoiceState]:
    member = SimpleNamespace(bot=False, guild=SimpleNamespace(id=guild_id), display_name="u")
    return (
        cast(discord.Member, member),
        cast(discord.VoiceState, SimpleNamespace(channel=before)),
        cast(discord.VoiceState, SimpleNamespace(channel=after)),
    )


async def test_autojoin_joins_registered_vc_once(
    cog: TTS, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """登録 VC に同時に2人入っても接続は1回で、読み上げ先が登録されること"""
    cog.guild_settings = GuildSettingsStore(tmp_path / "gs.json")
    cog.guild_settings.set_autojoin(1, 10, 20)
    channels = _FakeChannelStore()
    monkeypatch.setattr(cog, "channel_store", channels)
    monkeypatch.setattr(cog, "_enqueue_announce", lambda gid, text: None)

    connected: dict[int, object] = {}
    joins: list[object] = []

    async def fake_join(channel: object):
        joins.append(channel)
        await asyncio.sleep(0.01)
        connected[1] = object()
        return connected[1], True

    monkeypatch.setattr(tts_mod, "_voice_client", lambda guild: connected.get(guild.id))
    monkeypatch.setattr(cog, "_join_vc", fake_join)

    vc = SimpleNamespace(id=10)
    await asyncio.gather(
        cog._maybe_autojoin(*_voice_event(1, None, vc)),
        cog._maybe_autojoin(*_voice_event(1, None, vc)),
    )
    assert joins == [vc]
    assert channels.added == [(1, 20)]


async def test_autojoin_ignores_unregistered_vc(
    cog: TTS, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cog.guild_settings = GuildSettingsStore(tmp_path / "gs.json")
    cog.guild_settings.set_autojoin(1, 10, 20)

    async def fail_join(channel: object):
        raise AssertionError("joined unexpectedly")

    monkeypatch.setattr(tts_mod, "_voice_client", lambda guild: None)
    monkeypatch.setattr(cog, "_join_vc", fail_join)
    vc = SimpleNamespace(id=10)
    other = SimpleNamespace(id=11)
    await cog._maybe_autojoin(*_voice_event(1, None, other))
    await cog._maybe_autojoin(*_voice_event(1, vc, vc))
    await cog._maybe_autojoin(*_voice_event(1, vc, None))


async def test_ignored_user_message_is_not_read(
    cog: TTS, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cog.guild_settings = GuildSettingsStore(tmp_path / "gs.json")
    cog.guild_settings.add_ignored(1, 5)
    monkeypatch.setattr(cog, "channel_store", _FakeChannelStore({20}))
    queued: list[str] = []
    monkeypatch.setattr(cog, "_enqueue_item", lambda gid, item: queued.append(item.text))

    def message(author_id: int) -> discord.Message:
        return cast(discord.Message, SimpleNamespace(
            author=SimpleNamespace(id=author_id, bot=False),
            guild=SimpleNamespace(id=1, voice_client=object()),
            channel=SimpleNamespace(id=20),
            content="こんにちは",
        ))

    await cog.on_message(message(5))
    await cog.on_message(message(6))
    assert queued == ["こんにちは"]
