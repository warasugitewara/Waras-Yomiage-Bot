"""ユーザーごとの読み上げスピーカー設定の永続化管理"""

import json
from pathlib import Path

_DATA_DIR = Path(__file__).parent / "data"
_USERS_FILE = _DATA_DIR / "users.json"


def _load() -> dict[str, int]:
    if _USERS_FILE.exists():
        try:
            with _USERS_FILE.open(encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save(data: dict[str, int]) -> None:
    _DATA_DIR.mkdir(exist_ok=True)
    with _USERS_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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
