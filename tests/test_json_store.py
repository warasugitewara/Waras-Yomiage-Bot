import json
from pathlib import Path

from channel_store import _validate_channels, _validate_dict
from json_store import load_json, save_json
from user_store import _validate_users


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "users.json"
    save_json(path, {"1": 3})
    assert load_json(path, _validate_users, {}) == {"1": 3}


def test_save_rotates_backups(tmp_path: Path) -> None:
    path = tmp_path / "users.json"
    for i in range(5):
        save_json(path, {"1": i})
    assert json.loads(path.read_text(encoding="utf-8")) == {"1": 4}
    assert json.loads(path.with_suffix(".bak1").read_text(encoding="utf-8")) == {"1": 3}
    assert json.loads(path.with_suffix(".bak3").read_text(encoding="utf-8")) == {"1": 1}
    assert not path.with_suffix(".bak4").exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_broken_json_falls_back_to_backup(tmp_path: Path) -> None:
    path = tmp_path / "users.json"
    save_json(path, {"1": 3})
    save_json(path, {"1": 5})
    path.write_text("{broken", encoding="utf-8")
    assert load_json(path, _validate_users, {}) == {"1": 3}


def test_schema_mismatch_falls_back_to_backup(tmp_path: Path) -> None:
    path = tmp_path / "users.json"
    save_json(path, {"1": 3})
    save_json(path, {"1": "not-int"})
    assert load_json(path, _validate_users, {}) == {"1": 3}


def test_missing_files_return_default(tmp_path: Path) -> None:
    assert load_json(tmp_path / "none.json", _validate_users, {}) == {}


def test_validate_channels() -> None:
    assert _validate_channels({"10": [1, 2]}) == {10: {1, 2}}
    assert _validate_channels({"abc": [1]}) is None
    assert _validate_channels({"10": ["1"]}) is None
    assert _validate_channels([]) is None


def test_validate_dict() -> None:
    assert _validate_dict({"10": {"a": "b"}}) == {10: {"a": "b"}}
    assert _validate_dict({"10": {"a": 1}}) is None
    assert _validate_dict({"x": {}}) is None


def test_validate_users_rejects_bool() -> None:
    assert _validate_users({"1": True}) is None
