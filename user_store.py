"""ユーザーごとの読み上げスピーカー設定の永続化管理"""

import json
import os
import shutil
import tempfile
from pathlib import Path

_DATA_DIR = Path(__file__).parent / "data"
_USERS_FILE = _DATA_DIR / "users.json"
_BACKUP_COUNT = 3


def _rotate_backups(path: Path) -> None:
    """最大 _BACKUP_COUNT 世代のバックアップをローテーションする。
    liveファイルはコピーして保持（rename しない）。
    """
    if not path.exists():
        return
    for i in range(_BACKUP_COUNT - 1, 0, -1):
        src = path.with_suffix(f".bak{i}")
        dst = path.with_suffix(f".bak{i + 1}")
        if src.exists():
            src.replace(dst)
    shutil.copy2(str(path), str(path.with_suffix(".bak1")))


def _load() -> dict[str, int]:
    """main → bak1 → bak2 → bak3 の順にフォールバックして読み込む"""
    paths = [_USERS_FILE] + [
        _USERS_FILE.with_suffix(f".bak{i}") for i in range(1, _BACKUP_COUNT + 1)
    ]
    for p in paths:
        if not p.exists():
            continue
        try:
            with p.open(encoding="utf-8") as f:
                data = json.load(f)
            # 型バリデーション: {str → int} のみ受け入れる
            if isinstance(data, dict) and all(
                isinstance(k, str) and isinstance(v, int) for k, v in data.items()
            ):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save(data: dict[str, int]) -> None:
    """atomic write: temp→fsync→rotate→replace→dir_fsync"""
    _DATA_DIR.mkdir(exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=_DATA_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        _rotate_backups(_USERS_FILE)
        os.replace(tmp_path, _USERS_FILE)
        # ディレクトリエントリの永続化（POSIX）
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
