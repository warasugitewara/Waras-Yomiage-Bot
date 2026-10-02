"""ギルドごとの自動参加・除外ユーザー設定の永続化管理"""

from dataclasses import dataclass, field
from pathlib import Path

from json_store import load_json, save_json

_DATA_DIR = Path(__file__).parent / "data"
_SETTINGS_FILE = _DATA_DIR / "guild_settings.json"


def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_id_str(v: object) -> bool:
    return isinstance(v, str) and v.isdigit()


@dataclass
class GuildSettings:
    # 自動参加: VC の channel_id → 読み上げるテキストチャンネルの channel_id
    autojoin: dict[int, int] = field(default_factory=dict)
    # 読み上げ対象外のユーザーID
    ignored: set[int] = field(default_factory=set)
    # 読み上げ時に発言者名を先頭に付けるか（標準は OFF）
    read_name: bool = False

    def is_empty(self) -> bool:
        return not self.autojoin and not self.ignored and not self.read_name


def _validate_settings(raw: object) -> dict[int, GuildSettings] | None:
    """{guild_id(str): {"autojoin": {vc_id(str): text_id(int)}, "ignored": [user_id(int)], "read_name": bool}} のみ受け入れる"""
    if not isinstance(raw, dict):
        return None
    result: dict[int, GuildSettings] = {}
    for gid, entry in raw.items():
        if not (_is_id_str(gid) and isinstance(entry, dict)):
            return None
        autojoin = entry.get("autojoin", {})
        ignored = entry.get("ignored", [])
        read_name = entry.get("read_name", False)
        if not isinstance(autojoin, dict) or not isinstance(ignored, list) or not isinstance(read_name, bool):
            return None
        if not all(_is_id_str(k) and _is_int(v) for k, v in autojoin.items()):
            return None
        if not all(_is_int(u) for u in ignored):
            return None
        result[int(gid)] = GuildSettings(
            autojoin={int(k): v for k, v in autojoin.items()},
            ignored=set(ignored),
            read_name=read_name,
        )
    return result


class GuildSettingsStore:
    """ギルドごとの自動参加 VC と除外ユーザーを管理する"""

    def __init__(self, path: Path = _SETTINGS_FILE):
        self._path = path
        self._data: dict[int, GuildSettings] = load_json(path, _validate_settings, {})

    def _save(self):
        save_json(
            self._path,
            {
                str(gid): {
                    "autojoin": {str(vc): text for vc, text in s.autojoin.items()},
                    "ignored": sorted(s.ignored),
                    "read_name": s.read_name,
                }
                for gid, s in self._data.items()
            },
        )

    def _get(self, guild_id: int) -> GuildSettings:
        return self._data.setdefault(guild_id, GuildSettings())

    def _prune(self, guild_id: int):
        s = self._data.get(guild_id)
        if s is not None and s.is_empty():
            del self._data[guild_id]

    def clear(self, guild_id: int) -> None:
        """ギルドの設定をすべて削除する（サーバーから退出したとき）"""
        if self._data.pop(guild_id, None) is not None:
            self._save()

    # ---- 自動参加 ----

    def set_autojoin(self, guild_id: int, vc_id: int, text_id: int) -> None:
        """自動参加 VC を登録（既存なら読み上げ先を上書き）"""
        self._get(guild_id).autojoin[vc_id] = text_id
        self._save()

    def remove_autojoin(self, guild_id: int, vc_id: int) -> bool:
        """自動参加 VC を解除。登録されていなかった場合は False"""
        s = self._data.get(guild_id)
        if s is None or vc_id not in s.autojoin:
            return False
        del s.autojoin[vc_id]
        self._prune(guild_id)
        self._save()
        return True

    def autojoin_text(self, guild_id: int, vc_id: int) -> int | None:
        """VC が自動参加対象なら読み上げ先テキストチャンネルIDを返す"""
        s = self._data.get(guild_id)
        return s.autojoin.get(vc_id) if s else None

    def autojoin_all(self, guild_id: int) -> dict[int, int]:
        s = self._data.get(guild_id)
        return dict(s.autojoin) if s else {}

    # ---- 除外ユーザー ----

    def add_ignored(self, guild_id: int, user_id: int) -> bool:
        """除外ユーザーに追加。既に除外済みなら False"""
        ignored = self._get(guild_id).ignored
        if user_id in ignored:
            return False
        ignored.add(user_id)
        self._save()
        return True

    def remove_ignored(self, guild_id: int, user_id: int) -> bool:
        """除外を解除。除外されていなかった場合は False"""
        s = self._data.get(guild_id)
        if s is None or user_id not in s.ignored:
            return False
        s.ignored.discard(user_id)
        self._prune(guild_id)
        self._save()
        return True

    def toggle_ignored(self, guild_id: int, user_id: int) -> bool:
        """除外状態を切り替え、切り替え後に除外中なら True"""
        if self.remove_ignored(guild_id, user_id):
            return False
        self.add_ignored(guild_id, user_id)
        return True

    def is_ignored(self, guild_id: int, user_id: int) -> bool:
        s = self._data.get(guild_id)
        return s is not None and user_id in s.ignored

    def ignored_all(self, guild_id: int) -> set[int]:
        s = self._data.get(guild_id)
        return set(s.ignored) if s else set()

    # ---- 名前読み上げ ----

    def set_read_name(self, guild_id: int, enabled: bool) -> None:
        self._get(guild_id).read_name = enabled
        self._prune(guild_id)
        self._save()

    def read_name(self, guild_id: int) -> bool:
        s = self._data.get(guild_id)
        return s is not None and s.read_name
