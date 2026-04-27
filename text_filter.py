"""メッセージの前処理フィルター"""

import re


# URL パターン
_URL_RE = re.compile(r"https?://\S+")

# Discord メンション (<@123>, <@!123>, <#123>, <@&123>)
_MENTION_RE = re.compile(r"<(?:@[!&]?|#)\d+>")

# カスタム絵文字 <:name:id> <a:name:id>
_EMOJI_RE = re.compile(r"<a?:\w+:\d+>")

# 連続する改行・空白を1つに
_WHITESPACE_RE = re.compile(r"\s+")


def filter_message(
    text: str,
    word_dict: dict[str, str],
    max_length: int = 100,
) -> str | None:
    """
    メッセージを読み上げ用テキストに変換する。
    読み上げ不要な場合は None を返す。
    """
    # 空文字・空白のみは無視
    text = text.strip()
    if not text:
        return None

    # URL を「URL省略」に置換
    text = _URL_RE.sub("URL省略", text)

    # メンションを除去
    text = _MENTION_RE.sub("", text)

    # カスタム絵文字をコロン付き名前に（例: <:smile:123> → smile）
    text = _EMOJI_RE.sub(lambda m: m.group(0).split(":")[1], text)

    # 読み替え辞書を適用（大文字小文字区別なし）
    # ASCII のみの単語は \b で単語境界を付けて部分一致を防ぐ
    for word, reading in word_dict.items():
        pat = (
            rf"\b{re.escape(word)}\b"
            if re.fullmatch(r"[a-zA-Z0-9]+", word)
            else re.escape(word)
        )
        text = re.sub(pat, reading, text, flags=re.IGNORECASE)

    # 連続空白を整理
    text = _WHITESPACE_RE.sub(" ", text).strip()

    # 空になったら無視
    if not text:
        return None

    # 長文カット
    if len(text) > max_length:
        text = text[:max_length] + "、以下省略"

    return text
