"""メッセージの前処理フィルター"""

import re


# URL パターン
_URL_RE = re.compile(r"https?://\S+")

# URL サービス分類テーブル（マッチ順に評価）
_URL_LABELS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"https?://(?:www\.)?github\.com/",         re.IGNORECASE), "GitHubリンク"),
    (re.compile(r"https?://(?:www\.)?youtu(?:\.be|be\.com)/", re.IGNORECASE), "YouTubeリンク"),
    (re.compile(r"https?://(?:www\.)?(?:twitter|x)\.com/", re.IGNORECASE), "Twitterリンク"),
    (re.compile(r"https?://(?:www\.)?twitch\.tv/",          re.IGNORECASE), "Twitchリンク"),
    (re.compile(r"https?://(?:www\.)?discord\.(?:com|gg)/", re.IGNORECASE), "Discordリンク"),
    (re.compile(r"https?://(?:www\.)?amazon\.(?:co\.jp|com)/", re.IGNORECASE), "Amazonリンク"),
    (re.compile(r"https?://(?:www\.)?nicovideo\.jp/",       re.IGNORECASE), "ニコニコリンク"),
    (re.compile(r"https?://(?:www\.)?pixiv\.net/",          re.IGNORECASE), "Pixivリンク"),
    (re.compile(r"https?://(?:www\.)?steamcommunity\.com/", re.IGNORECASE), "Steamリンク"),
]


def _classify_url(m: re.Match) -> str:
    url = m.group(0)
    for pattern, label in _URL_LABELS:
        if pattern.match(url):
            return label
    return "URLリンク"

# Discord メンション (<@123>, <@!123>, <#123>, <@&123>)
_MENTION_RE = re.compile(r"<(?:@[!&]?|#)\d+>")

# カスタム絵文字 <:name:id> <a:name:id>
_EMOJI_RE = re.compile(r"<a?:\w+:\d+>")

# 連続する改行・空白を1つに
_WHITESPACE_RE = re.compile(r"\s+")

# ASCII英数字のみの単語（単語境界適用対象の判定用）
_ASCII_WORD_RE = re.compile(r"^[a-zA-Z0-9]+$")


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

    # URL をサービス名に置換（GitHub/YouTube 等は識別、その他は「URLリンク」）
    text = _URL_RE.sub(_classify_url, text)

    # メンションを除去
    text = _MENTION_RE.sub("", text)

    # カスタム絵文字をコロン付き名前に（例: <:smile:123> → smile）
    text = _EMOJI_RE.sub(lambda m: m.group(0).split(":")[1], text)

    # 読み替え辞書を適用（大文字小文字区別なし）
    # ASCII のみの単語は \b で単語境界を付けて部分一致を防ぐ
    for word, reading in word_dict.items():
        pat = (
            rf"\b{re.escape(word)}\b"
            if _ASCII_WORD_RE.fullmatch(word)
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
