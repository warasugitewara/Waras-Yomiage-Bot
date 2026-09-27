"""JSON ファイルの永続化共通処理（atomic write・世代バックアップ・スキーマ検証付き読み込み）"""

import json
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

_BACKUP_COUNT = 3

T = TypeVar("T")


def _backup_path(path: Path, i: int) -> Path:
    return path.with_suffix(f".bak{i}")


def _rotate_backups(path: Path) -> None:
    """最大 _BACKUP_COUNT 世代のバックアップをローテーションする。
    liveファイルはコピーして保持（rename しない）。
    """
    if not path.exists():
        return
    for i in range(_BACKUP_COUNT - 1, 0, -1):
        src = _backup_path(path, i)
        if src.exists():
            src.replace(_backup_path(path, i + 1))
    shutil.copy2(str(path), str(_backup_path(path, 1)))


def load_json(path: Path, validate: Callable[[object], T | None], default: T) -> T:
    """main → bak1 → bak2 → bak3 の順にフォールバックして読み込む。

    validate は読み込んだ値を検証・変換し、不正なら None を返す。
    壊れた JSON だけでなくスキーマ不一致のファイルも次の世代へフォールバックする。
    """
    paths = [path] + [_backup_path(path, i) for i in range(1, _BACKUP_COUNT + 1)]
    for p in paths:
        if not p.exists():
            continue
        try:
            with p.open(encoding="utf-8") as f:
                result = validate(json.load(f))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            continue
        if result is not None:
            return result
        print(f"[STORE] スキーマ不一致のためスキップ: {p.name}")
    return default


def save_json(path: Path, data: object) -> None:
    """atomic write: temp→fsync→rotate→replace→dir_fsync"""
    data_dir = path.parent
    data_dir.mkdir(exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=data_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        _rotate_backups(path)
        os.replace(tmp_path, path)
        # ディレクトリエントリの永続化（POSIX）
        try:
            dir_fd = os.open(str(data_dir), os.O_RDONLY)
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
