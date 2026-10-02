"""環境変数から読み込む設定を一元管理する。

起動時に 1 回だけ読み込んで検証し、不正な値はどの変数が原因かわかるエラーで止める。
"""

import functools
import os
from collections.abc import Mapping
from dataclasses import dataclass, field

_BOT_STATUSES = ("online", "idle", "dnd", "invisible")
_TRUE_VALUES = ("true", "1", "yes", "on")
_FALSE_VALUES = ("false", "0", "no", "off", "")


class ConfigError(ValueError):
    """環境変数の値が不正"""


@dataclass(frozen=True)
class Config:
    # トークンはログや repr に出さない
    discord_token: str | None = field(default=None, repr=False)
    prefix: str = "!"
    voicevox_url: str = "http://localhost:50021"
    default_speaker: int = 3
    default_speed: float = 1.0
    max_text_length: int = 100
    guild_id: int | None = None
    owner_ids: frozenset[int] = frozenset()
    bot_status: str = "online"
    health_enabled: bool = False
    # Webhook / Push URL はトークンを含むため repr に出さない
    error_webhook_url: str | None = field(default=None, repr=False)
    uptime_kuma_push_url: str | None = field(default=None, repr=False)
    custom_url_labels: str = ""
    # 使用を許可するスピーカーID（None は制限なし）
    allowed_speakers: frozenset[int] | None = None

    def is_speaker_allowed(self, speaker_id: int) -> bool:
        return self.allowed_speakers is None or speaker_id in self.allowed_speakers


def _get(env: Mapping[str, str], name: str) -> str | None:
    """未設定・空文字は None として扱う"""
    value = env.get(name, "").strip()
    return value or None


def _int(env: Mapping[str, str], name: str, default: int, minimum: int, maximum: int | None = None) -> int:
    raw = _get(env, name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} は整数で指定してください（現在: {raw!r}）") from None
    if value < minimum or (maximum is not None and value > maximum):
        upper = f"〜{maximum}" if maximum is not None else " 以上"
        raise ConfigError(f"{name} は {minimum}{upper} の範囲で指定してください（現在: {value}）")
    return value


def _float(env: Mapping[str, str], name: str, default: float, minimum: float, maximum: float) -> float:
    raw = _get(env, name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} は数値で指定してください（現在: {raw!r}）") from None
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} は {minimum}〜{maximum} の範囲で指定してください（現在: {value}）")
    return value


def _bool(env: Mapping[str, str], name: str) -> bool:
    raw = env.get(name, "").strip().lower()
    if raw in _TRUE_VALUES:
        return True
    if raw in _FALSE_VALUES:
        return False
    raise ConfigError(f"{name} は true / false で指定してください（現在: {raw!r}）")


def _owner_ids(env: Mapping[str, str]) -> frozenset[int]:
    raw = _get(env, "OWNER_IDS")
    if raw is None:
        return frozenset()
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise ConfigError(f"OWNER_IDS はユーザーIDをカンマ区切りで指定してください（不正な値: {part!r}）")
        ids.add(int(part))
    return frozenset(ids)


def _allowed_speakers(env: Mapping[str, str]) -> frozenset[int] | None:
    raw = _get(env, "ALLOWED_SPEAKERS")
    if raw is None:
        return None
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise ConfigError(f"ALLOWED_SPEAKERS はスピーカーIDをカンマ区切りで指定してください（不正な値: {part!r}）")
        ids.add(int(part))
    return frozenset(ids) if ids else None


def _guild_id(env: Mapping[str, str]) -> int | None:
    raw = _get(env, "GUILD_ID")
    if raw is None:
        return None
    if not raw.isdigit():
        raise ConfigError(f"GUILD_ID はサーバーIDで指定してください（現在: {raw!r}）")
    return int(raw)


def _bot_status(env: Mapping[str, str]) -> str:
    raw = (_get(env, "BOT_STATUS") or "online").lower()
    if raw not in _BOT_STATUSES:
        raise ConfigError(f"BOT_STATUS は {' / '.join(_BOT_STATUSES)} のいずれかで指定してください（現在: {raw!r}）")
    return raw


def load_config(env: Mapping[str, str] | None = None) -> Config:
    """環境変数から設定を読み込んで検証する。不正な値があれば ConfigError"""
    env = os.environ if env is None else env
    allowed_speakers = _allowed_speakers(env)
    default_speaker = _int(env, "DEFAULT_SPEAKER", 3, minimum=0)
    if allowed_speakers is not None and default_speaker not in allowed_speakers:
        raise ConfigError(
            f"DEFAULT_SPEAKER（{default_speaker}）が ALLOWED_SPEAKERS に含まれていません"
        )
    return Config(
        discord_token=_get(env, "DISCORD_TOKEN"),
        prefix=_get(env, "PREFIX") or "!",
        voicevox_url=_get(env, "VOICEVOX_URL") or "http://localhost:50021",
        default_speaker=default_speaker,
        default_speed=_float(env, "DEFAULT_SPEED", 1.0, minimum=0.5, maximum=2.0),
        max_text_length=_int(env, "MAX_TEXT_LENGTH", 100, minimum=1, maximum=2000),
        guild_id=_guild_id(env),
        owner_ids=_owner_ids(env),
        bot_status=_bot_status(env),
        health_enabled=_bool(env, "HEALTH_ENABLED"),
        error_webhook_url=_get(env, "ERROR_WEBHOOK_URL"),
        uptime_kuma_push_url=_get(env, "UPTIME_KUMA_PUSH_URL"),
        custom_url_labels=_get(env, "CUSTOM_URL_LABELS") or "",
        allowed_speakers=allowed_speakers,
    )


@functools.cache
def get_config() -> Config:
    """プロセス全体で共有する設定（初回呼び出し時に読み込む。load_dotenv() の後に呼ぶこと）"""
    return load_config()
