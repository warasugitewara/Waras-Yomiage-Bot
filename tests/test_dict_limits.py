from cogs.dictionary import (
    Dictionary,
    _DICT_MAX_ENTRIES,
    _DICT_READING_MAX_LEN,
    _DICT_WORD_MAX_LEN,
    _validate_dict_entry,
)


def test_valid_entry_passes() -> None:
    assert _validate_dict_entry("東京", "とうきょう") is None


def test_blank_word_is_rejected() -> None:
    assert _validate_dict_entry("  ", "x") is not None


def test_too_long_word_is_rejected() -> None:
    assert _validate_dict_entry("a" * _DICT_WORD_MAX_LEN, "x") is None
    assert _validate_dict_entry("a" * (_DICT_WORD_MAX_LEN + 1), "x") is not None


def test_too_long_reading_is_rejected() -> None:
    assert _validate_dict_entry("a", "x" * _DICT_READING_MAX_LEN) is None
    assert _validate_dict_entry("a", "x" * (_DICT_READING_MAX_LEN + 1)) is not None


def test_import_rejects_whole_file_on_invalid_entry() -> None:
    entries = {"ok": "おけ", "a" * (_DICT_WORD_MAX_LEN + 1): "x"}
    assert Dictionary._check_dict_import(entries, {}) is not None


def test_import_counts_merged_total() -> None:
    current = {f"w{i}": "x" for i in range(_DICT_MAX_ENTRIES)}
    # 既存キーの更新のみなら上限内
    assert Dictionary._check_dict_import({"w0": "y"}, current) is None
    # 新規キーが1件でも増えれば超過
    assert Dictionary._check_dict_import({"new": "y"}, current) is not None


def test_import_replace_ignores_current() -> None:
    entries = {f"n{i}": "x" for i in range(_DICT_MAX_ENTRIES)}
    assert Dictionary._check_dict_import(entries, {}) is None
    entries["extra"] = "x"
    assert Dictionary._check_dict_import(entries, {}) is not None
