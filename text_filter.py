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

# 5文字以上連続する同一文字（横方向スパム抑制）
_REPEAT_RE = re.compile(r"(.)\1{4,}")

# ASCII英数字のみの単語（単語境界適用対象の判定用）
_ASCII_WORD_RE = re.compile(r"^[a-zA-Z0-9]+$")

# 縦方向スパムで連続する同一行を最大3行に圧縮
_LINE_MAX_REPEAT = 3


def _collapse_repeated_lines(text: str) -> str:
    """改行で繰り返される同一行を最大 _LINE_MAX_REPEAT 行に圧縮する。

    例:
        "w\\nw\\nw\\nw\\nw" → "w\\nw\\nw"
        "草\\n草\\n草\\n草" → "草\\n草\\n草"
    空行・空白のみの行は比較対象から除外（ただし出力には含めない）。
    """
    lines = text.splitlines()
    result: list[str] = []
    prev_stripped: str | None = None
    count = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue  # 空行は捨てる（後続の whitespace collapse でどうせ消える）
        if stripped == prev_stripped:
            count += 1
        else:
            count = 1
            prev_stripped = stripped
        if count <= _LINE_MAX_REPEAT:
            result.append(stripped)   # stripped を使って余分な空白も除去
    return " ".join(result)           # 改行ではなく半角スペースで連結


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
    if word_dict:
        # 単語境界が必要なものと不要なものを分けて正規表現を構築
        boundary_words = []
        normal_words = []
        for word in word_dict:
            if _ASCII_WORD_RE.fullmatch(word):
                boundary_words.append(re.escape(word))
            else:
                normal_words.append(re.escape(word))
        
        patterns = []
        if boundary_words:
            patterns.append(rf"\b({'|'.join(boundary_words)})\b")
        if normal_words:
            patterns.append(f"({'|'.join(normal_words)})")
        
        if patterns:
            combined_pat = re.compile("|".join(patterns), re.IGNORECASE)
            lower_dict = {k.lower(): v for k, v in word_dict.items()}
            
            def _dict_replace(m: re.Match) -> str:
                return lower_dict.get(m.group(0).lower(), m.group(0))

            text = combined_pat.sub(_dict_replace, text)

    # 縦方向スパム: 同じ行が3行以上連続する場合に圧縮
    text = _collapse_repeated_lines(text)

    # 連続空白を整理（改行もスペースに正規化）
    text = _WHITESPACE_RE.sub(" ", text).strip()

    # 横方向スパム: 同一文字の5連打以上を3文字に圧縮（wwwww→www、！！！！→！！！）
    text = _REPEAT_RE.sub(lambda m: m.group(1) * 3, text)

    # 空になったら無視
    if not text:
        return None

    # 長文カット
    if len(text) > max_length:
        text = text[:max_length] + "、以下省略"

    return text
