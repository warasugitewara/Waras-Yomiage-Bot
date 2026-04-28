"""読み上げチャンネルと読み替え辞書の永続化管理"""

import json
import os
import shutil
import tempfile
from pathlib import Path

_DATA_DIR = Path(__file__).parent / "data"
_CHANNELS_FILE = _DATA_DIR / "channels.json"
_DICT_FILE = _DATA_DIR / "dict.json"
_BACKUP_COUNT = 3


def _rotate_backups(path: Path) -> None:
    if not path.exists():
        return
    for i in range(_BACKUP_COUNT - 1, 0, -1):
        src = path.with_suffix(f".bak{i}")
        dst = path.with_suffix(f".bak{i + 1}")
        if src.exists():
            src.replace(dst)
    shutil.copy2(str(path), str(path.with_suffix(".bak1")))


def _load_json(path: Path, default) -> dict:
    """main → bak1 → bak2 → bak3 の順にフォールバックして読み込む"""
    paths = [path] + [path.with_suffix(f".bak{i}") for i in range(1, _BACKUP_COUNT + 1)]
    for p in paths:
        if not p.exists():
            continue
        try:
            with p.open(encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return default


def _save_json(path: Path, data) -> None:
    """atomic write: temp→fsync→rotate→replace→dir_fsync"""
    _DATA_DIR.mkdir(exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=_DATA_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        _rotate_backups(path)
        os.replace(tmp_path, path)
        try:
            dir_fd = os.open(str(_DATA_DIR), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


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
    """ギルドごとの読み替え辞書を管理する"""

    def __init__(self):
        raw = _load_json(_DICT_FILE, {})
        # guild_id(str) → {word: reading}
        self._data: dict[int, dict[str, str]] = {
            int(gid): d for gid, d in raw.items() if isinstance(d, dict)
        }

    def _save(self):
        _save_json(_DICT_FILE, {str(gid): d for gid, d in self._data.items()})

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
