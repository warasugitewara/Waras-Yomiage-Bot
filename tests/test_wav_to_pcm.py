import io
import wave

from cogs.tts import _extract_discord_pcm


def _make_wav(rate: int, channels: int, frames: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)
    return buf.getvalue()


def test_discord_format_is_passed_through() -> None:
    frames = bytes(range(8)) * 10
    assert _extract_discord_pcm(_make_wav(48000, 2, frames)) == frames


def test_other_format_falls_back() -> None:
    assert _extract_discord_pcm(_make_wav(24000, 1, b"\x00\x01" * 10)) is None


def test_empty_or_broken_falls_back() -> None:
    assert _extract_discord_pcm(_make_wav(48000, 2, b"")) is None
    assert _extract_discord_pcm(b"not a wav") is None
