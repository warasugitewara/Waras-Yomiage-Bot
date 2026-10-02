import pytest

from config import ConfigError, load_config


def test_defaults_when_unset() -> None:
    c = load_config({})
    assert c.prefix == "!"
    assert c.voicevox_url == "http://localhost:50021"
    assert (c.default_speaker, c.default_speed, c.max_text_length) == (3, 1.0, 100)
    assert c.guild_id is None and c.owner_ids == frozenset()
    assert c.bot_status == "online" and not c.health_enabled
    assert c.discord_token is None and c.error_webhook_url is None


def test_values_are_parsed() -> None:
    c = load_config({
        "DISCORD_TOKEN": "secret",
        "PREFIX": "!y",
        "DEFAULT_SPEAKER": "46",
        "DEFAULT_SPEED": "1.2",
        "MAX_TEXT_LENGTH": "200",
        "GUILD_ID": "123",
        "OWNER_IDS": "1, 2,",
        "BOT_STATUS": "IDLE",
        "HEALTH_ENABLED": "true",
        "ERROR_WEBHOOK_URL": "  ",
    })
    assert c.prefix == "!y"
    assert (c.default_speaker, c.default_speed, c.max_text_length) == (46, 1.2, 200)
    assert c.guild_id == 123 and c.owner_ids == frozenset({1, 2})
    assert c.bot_status == "idle" and c.health_enabled
    assert c.error_webhook_url is None  # 空白のみは未設定扱い
    assert "secret" not in repr(c)  # トークンを repr に出さない


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("DEFAULT_SPEAKER", "abc"),
        ("DEFAULT_SPEAKER", "-1"),
        ("DEFAULT_SPEED", "3.0"),
        ("DEFAULT_SPEED", "fast"),
        ("MAX_TEXT_LENGTH", "0"),
        ("GUILD_ID", "my-guild"),
        ("OWNER_IDS", "1,abc"),
        ("BOT_STATUS", "away"),
        ("HEALTH_ENABLED", "maybe"),
    ],
)
def test_invalid_values_name_the_variable(name: str, value: str) -> None:
    with pytest.raises(ConfigError, match=name):
        load_config({name: value})
