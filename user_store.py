"""ユーザーごとの読み上げスピーカー設定の永続化管理"""

from pathlib import Path

from json_store import load_json, save_json

_DATA_DIR = Path(__file__).parent / "data"
_USERS_FILE = _DATA_DIR / "users.json"


def is_valid_entry(user_id: object, speaker_id: object) -> bool:
    """user_id は数字文字列、speaker_id は int（bool は int のサブクラスなので除外）"""
    return (
        isinstance(user_id, str)
        and user_id.isdigit()
        and isinstance(speaker_id, int)
        and not isinstance(speaker_id, bool)
    )


def _validate_users(raw: object) -> dict[str, int] | None:
    """{user_id(str): speaker_id(int)} のみ受け入れる"""
    if isinstance(raw, dict) and all(is_valid_entry(k, v) for k, v in raw.items()):
        return raw
    return None


def _load() -> dict[str, int]:
    return load_json(_USERS_FILE, _validate_users, {})


def _save(data: dict[str, int]) -> None:
    save_json(_USERS_FILE, data)


class UserVoiceStore:
    """ユーザーごとの VOICEVOX speaker_id を管理する。スコープはグローバル（全サーバー共通）"""

    def __init__(self, default_speaker: int = 3):
        self.default_speaker = default_speaker
        # user_id(str) → speaker_id(int)
        self._data: dict[str, int] = _load()

    def get(self, user_id: int) -> int:
        """ユーザーの speaker_id を返す。未設定なら default_speaker"""
        return self._data.get(str(user_id), self.default_speaker)

    def set(self, user_id: int, speaker_id: int) -> None:
        self._data[str(user_id)] = speaker_id
        _save(self._data)

    def reset(self, user_id: int) -> bool:
        """設定をリセット。存在しなかった場合は False"""
        if str(user_id) not in self._data:
            return False
        del self._data[str(user_id)]
        _save(self._data)
        return True

    def export_all(self) -> dict[str, int]:
        """全ユーザー設定を {user_id_str: speaker_id} で返す（コピー）"""
        return dict(self._data)

    def import_all(self, entries: dict[str, int], replace: bool = False) -> int:
        """ユーザー設定をインポート。replace=True で全置換。追加/更新件数を返す"""
        if replace:
            self._data = dict(entries)
        else:
            self._data.update(entries)
        _save(self._data)
        return len(entries)
