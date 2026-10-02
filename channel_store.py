"""読み上げチャンネルと読み替え辞書の永続化管理"""

from pathlib import Path

from json_store import load_json, save_json
from text_filter import WordDictItems

_DATA_DIR = Path(__file__).parent / "data"
_CHANNELS_FILE = _DATA_DIR / "channels.json"
_DICT_FILE = _DATA_DIR / "dict.json"


def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _validate_channels(raw: object) -> dict[int, set[int]] | None:
    """{guild_id(str): [channel_id(int), ...]} のみ受け入れる"""
    if not isinstance(raw, dict):
        return None
    result: dict[int, set[int]] = {}
    for gid, cids in raw.items():
        if not (isinstance(gid, str) and gid.isdigit() and isinstance(cids, list)):
            return None
        if not all(_is_int(c) for c in cids):
            return None
        result[int(gid)] = set(cids)
    return result


def _validate_dict(raw: object) -> dict[int, dict[str, str]] | None:
    """{guild_id(str): {word(str): reading(str)}} のみ受け入れる"""
    if not isinstance(raw, dict):
        return None
    result: dict[int, dict[str, str]] = {}
    for gid, d in raw.items():
        if not (isinstance(gid, str) and gid.isdigit() and isinstance(d, dict)):
            return None
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in d.items()):
            return None
        result[int(gid)] = d
    return result


class ChannelStore:
    """ギルドごとの読み上げチャンネルセットを管理する"""

    def __init__(self):
        # guild_id → set[channel_id]
        self._data: dict[int, set[int]] = load_json(_CHANNELS_FILE, _validate_channels, {})

    def _save(self):
        save_json(
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
    """ギルドごとの読み替え辞書を管理する"""

    def __init__(self):
        # guild_id → {word: reading}
        self._data: dict[int, dict[str, str]] = load_json(_DICT_FILE, _validate_dict, {})
        # guild_id → 辞書の frozenset（メッセージごとの複製を避けるため、変更時のみ作り直す）
        self._items_cache: dict[int, WordDictItems] = {}

    def _save(self):
        self._items_cache.clear()
        save_json(_DICT_FILE, {str(gid): d for gid, d in self._data.items()})

    def _guild_dict(self, guild_id: int) -> dict[str, str]:
        return self._data.setdefault(guild_id, {})

    def add(self, guild_id: int, word: str, reading: str) -> None:
        self._guild_dict(guild_id)[word] = reading
        self._save()

    def remove(self, guild_id: int, word: str) -> bool:
        d = self._data.get(guild_id, {})
        if word not in d:
            return False
        del d[word]
        if not d:
            self._data.pop(guild_id, None)
        self._save()
        return True

    def all(self, guild_id: int) -> dict[str, str]:
        return dict(self._data.get(guild_id, {}))

    def items(self, guild_id: int) -> WordDictItems:
        """読み上げ用の辞書スナップショット（変更されるまで同じオブジェクトを返す）"""
        cached = self._items_cache.get(guild_id)
        if cached is None:
            cached = frozenset(self._data.get(guild_id, {}).items())
            self._items_cache[guild_id] = cached
        return cached

    def import_dict(self, guild_id: int, entries: dict[str, str], replace: bool = False) -> int:
        """辞書をインポート。replace=True で既存を全置換。追加/更新件数を返す"""
        if replace:
            self._data[guild_id] = dict(entries)
        else:
            self._guild_dict(guild_id).update(entries)
        self._save()
        return len(entries)

    def export_dict(self, guild_id: int) -> dict[str, str]:
        return dict(self._data.get(guild_id, {}))
