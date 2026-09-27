from text_filter import filter_message


def test_empty_message_is_ignored() -> None:
    assert filter_message("   ", {}) is None


def test_url_is_labeled() -> None:
    assert filter_message("見て https://github.com/foo/bar", {}) == "見て GitHubリンク"
    assert filter_message("https://example.com/x", {}) == "URLリンク"


def test_mention_and_custom_emoji() -> None:
    assert filter_message("<@123> やあ <:smile:456>", {}) == "やあ smile"


def test_spoiler_and_codeblock_are_removed() -> None:
    assert filter_message("a ||ネタバレ|| b ```code``` c", {}) == "a b c"


def test_inline_code_content_is_read() -> None:
    assert filter_message("`ls` して", {}) == "ls して"


def test_horizontal_repeat_is_collapsed() -> None:
    assert filter_message("wwwwwww", {}) == "www"


def test_vertical_repeat_is_collapsed() -> None:
    assert filter_message("草\n草\n草\n草\n草", {}) == "草 草 草"


def test_long_text_is_truncated() -> None:
    assert filter_message("あいうえおかきくけこ", {}, max_length=5) == "あいうえお、以下省略"


def test_longest_dictionary_key_wins() -> None:
    d = {"東京": "とうきょう", "東京都": "とうきょうと"}
    assert filter_message("東京都", d) == "とうきょうと"


def test_ascii_dictionary_key_uses_word_boundaries() -> None:
    assert filter_message("cat scatter", {"cat": "ねこ"}) == "ねこ scatter"


def test_ascii_dictionary_key_is_case_insensitive() -> None:
    assert filter_message("CAT", {"cat": "ねこ"}) == "ねこ"


def test_empty_dictionary_key_is_ignored() -> None:
    assert filter_message("abc", {"": "x"}) == "abc"
