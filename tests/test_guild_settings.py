import json
from pathlib import Path

from guild_settings import GuildSettingsStore, _validate_settings


def test_validate_accepts_valid_settings() -> None:
    raw = {"1": {"autojoin": {"10": 20}, "ignored": [5, 6]}}
    result = _validate_settings(raw)
    assert result is not None
    assert result[1].autojoin == {10: 20}
    assert result[1].ignored == {5, 6}


def test_validate_rejects_invalid_settings() -> None:
    assert _validate_settings([]) is None
    assert _validate_settings({"x": {}}) is None
    assert _validate_settings({"1": {"autojoin": {"vc": 20}}}) is None
    assert _validate_settings({"1": {"autojoin": {"10": True}}}) is None
    assert _validate_settings({"1": {"ignored": ["5"]}}) is None


def test_autojoin_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "guild_settings.json"
    store = GuildSettingsStore(path)
    store.set_autojoin(1, 10, 20)
    store.set_autojoin(1, 10, 30)  # 同じ VC は読み上げ先を上書き

    reloaded = GuildSettingsStore(path)
    assert reloaded.autojoin_text(1, 10) == 30
    assert reloaded.autojoin_text(1, 99) is None
    assert reloaded.autojoin_text(2, 10) is None

    assert reloaded.remove_autojoin(1, 10)
    assert not reloaded.remove_autojoin(1, 10)
    assert reloaded.autojoin_all(1) == {}
    # 空になったギルドは保存データから消える
    assert json.loads(path.read_text(encoding="utf-8")) == {}


def test_ignored_add_remove_toggle(tmp_path: Path) -> None:
    path = tmp_path / "guild_settings.json"
    store = GuildSettingsStore(path)
    assert store.add_ignored(1, 5)
    assert not store.add_ignored(1, 5)
    assert store.is_ignored(1, 5)
    assert not store.is_ignored(2, 5)  # ギルドごとに独立

    assert not store.toggle_ignored(1, 5)  # 除外中 → 解除
    assert not store.is_ignored(1, 5)
    assert store.toggle_ignored(1, 5)  # 未除外 → 除外
    assert GuildSettingsStore(path).ignored_all(1) == {5}

    assert store.remove_ignored(1, 5)
    assert not store.remove_ignored(1, 5)
    assert json.loads(path.read_text(encoding="utf-8")) == {}



def test_read_name_defaults_off_and_persists(tmp_path: Path) -> None:
    path = tmp_path / "guild_settings.json"
    store = GuildSettingsStore(path)
    assert not store.read_name(1)
    store.set_read_name(1, True)
    assert GuildSettingsStore(path).read_name(1)
    store.set_read_name(1, False)
    assert json.loads(path.read_text(encoding="utf-8")) == {}
    assert _validate_settings({"1": {"read_name": "yes"}}) is None
