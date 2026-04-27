"""読み上げチャンネルと読み替え辞書の永続化管理"""

import json
import os
from pathlib import Path

_DATA_DIR = Path(__file__).parent / "data"
_CHANNELS_FILE = _DATA_DIR / "channels.json"
_DICT_FILE = _DATA_DIR / "dict.json"


def _load_json(path: Path, default) -> dict:
    if path.exists():
        try:
            with path.open(encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return default


def _save_json(path: Path, data) -> None:
    _DATA_DIR.mkdir(exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class ChannelStore:
    """ギルドごとの読み上げチャンネルセットを管理する"""

    def __init__(self):
        raw: dict[str, list[int]] = _load_json(_CHANNELS_FILE, {})
        # guild_id(str) → set[channel_id(int)]
        self._data: dict[int, set[int]] = {
            int(gid): set(cids) for gid, cids in raw.items()
        }

    def _save(self):
        _save_json(
            _CHANNELS_FILE,
            {str(gid): list(cids) for gid, cids in self._data.items()},
        )

    def add(self, guild_id: int, channel_id: int) -> bool:
        """チャンネルを追加。既に存在する場合は False"""
        channels = self._data.setdefault(guild_id, set())
        if channel_id in channels:
            return False
        channels.add(channel_id)
        self._save()
        return True

    def remove(self, guild_id: int, channel_id: int) -> bool:
        """チャンネルを削除。存在しなかった場合は False"""
        channels = self._data.get(guild_id, set())
        if channel_id not in channels:
            return False
        channels.discard(channel_id)
        if not channels:
            self._data.pop(guild_id, None)
        self._save()
        return True

    def get(self, guild_id: int) -> set[int]:
        """ギルドの読み上げチャンネルセットを返す"""
        return self._data.get(guild_id, set())

    def clear(self, guild_id: int):
        """ギルドの全チャンネルをクリア（/leave 時）"""
        self._data.pop(guild_id, None)
        self._save()

    def is_watched(self, guild_id: int, channel_id: int) -> bool:
        return channel_id in self._data.get(guild_id, set())


class WordDict:
    """読み替え辞書を管理する"""

    def __init__(self):
        self._data: dict[str, str] = _load_json(_DICT_FILE, {})

    def _save(self):
        _save_json(_DICT_FILE, self._data)

    def add(self, word: str, reading: str) -> None:
        self._data[word] = reading
        self._save()

    def remove(self, word: str) -> bool:
        if word not in self._data:
            return False
        del self._data[word]
        self._save()
        return True

    def all(self) -> dict[str, str]:
        return dict(self._data)
