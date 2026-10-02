"""レビュー報告書 R-1 / R-2 / R-3 の回帰テスト"""

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import discord
import pytest

import cogs.tts as tts_mod
from cogs.owner import Owner
from json_store import load_json, save_json
from user_store import _validate_users, is_valid_entry


# ---- R-2: bool を speaker_id として受け入れない


def test_is_valid_entry_rejects_bool() -> None:
    assert is_valid_entry("1", 3)
    assert not is_valid_entry("1", True)
    assert not is_valid_entry("x", 3)
    assert not is_valid_entry(1, 3)


def test_import_skips_bool_and_saved_data_survives_reload(tmp_path: Path) -> None:
    parsed = Owner._parse_users_json({
        "version": 1,
        "data": [
            {"user_id": "111", "speaker_id": 3},
            {"user_id": "333", "speaker_id": True},
        ],
    })
    assert parsed == {"111": 3}

    path = tmp_path / "users.json"
    save_json(path, parsed)
    assert load_json(path, _validate_users, {}) == {"111": 3}


# ---- R-1: 閲覧できないチャンネルを読み上げ対象にしない


class _FakeChannel:
    def __init__(self, viewers: set[int]) -> None:
        self.viewers = viewers

    def permissions_for(self, member: SimpleNamespace) -> SimpleNamespace:
        return SimpleNamespace(view_channel=member.id in self.viewers)


def _guild(channel: _FakeChannel | None, members: dict[int, SimpleNamespace]) -> discord.Guild:
    return cast(discord.Guild, SimpleNamespace(
        get_channel=lambda _cid: channel,
        get_member=lambda uid: members.get(uid),
    ))


def _member(uid: int, bot: bool = False) -> SimpleNamespace:
    return SimpleNamespace(id=uid, bot=bot)


def _user(uid: int) -> discord.abc.User:
    return cast(discord.abc.User, _member(uid))


def test_listen_rejects_channel_invisible_to_author(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tts_mod, "_voice_client", lambda _g: None)
    members = {1: _member(1), 2: _member(2)}
    guild = _guild(_FakeChannel({1}), members)
    assert tts_mod._listen_permission_error(guild, 10, _user(1)) is None
    assert tts_mod._listen_permission_error(guild, 10, _user(2)) is not None
    # 存在しないチャンネル ID
    assert tts_mod._listen_permission_error(_guild(None, members), 10, _user(1)) is not None


def test_listen_rejects_channel_invisible_to_vc_member(monkeypatch: pytest.MonkeyPatch) -> None:
    members = {1: _member(1), 2: _member(2)}
    vc_members = [_member(1), _member(2), _member(99, bot=True)]
    monkeypatch.setattr(
        tts_mod, "_voice_client",
        lambda _g: SimpleNamespace(channel=SimpleNamespace(members=vc_members)),
    )
    # Bot は閲覧権限の確認対象外
    assert tts_mod._listen_permission_error(_guild(_FakeChannel({1, 2}), members), 10, _user(1)) is None
    # VC 内のメンバー 2 が閲覧できない
    error = tts_mod._listen_permission_error(_guild(_FakeChannel({1}), members), 10, _user(1))
    assert error is not None and "VC 内" in error


# ---- R-3: メンション通知を飛ばさない


def test_bot_disables_all_mentions() -> None:
    from bot import YomiageBot

    am = YomiageBot().allowed_mentions
    assert am is not None
    assert not (am.everyone or am.roles or am.users or am.replied_user)


# ---- L-1: キャラクター別のクレジット表記


def test_credit_overrides() -> None:
    assert tts_mod.credit_for("ずんだもん") == "VOICEVOX:ずんだもん"
    assert tts_mod.credit_for("もち子さん") == "VOICEVOX:もち子(cv 明日葉よもぎ)"
    assert tts_mod.credit_for("里石ユカ") == "VOICEVOX:里石ユカ（つぼみ）"


# ---- L-4: サーバーから退出したらデータを削除する


async def test_guild_remove_deletes_guild_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import channel_store
    from guild_settings import GuildSettingsStore

    monkeypatch.setattr(channel_store, "_CHANNELS_FILE", tmp_path / "channels.json")
    monkeypatch.setattr(channel_store, "_DICT_FILE", tmp_path / "dict.json")
    bot = SimpleNamespace(user_voice_store=SimpleNamespace(get=lambda _uid: 3))
    from bot import YomiageBot

    cog = tts_mod.TTS(cast(YomiageBot, bot))
    cog.channel_store = channel_store.ChannelStore()
    cog.word_dict = channel_store.WordDict()
    cog.guild_settings = GuildSettingsStore(tmp_path / "gs.json")
    for gid in (1, 2):
        cog.channel_store.add(gid, 10)
        cog.word_dict.add(gid, "cat", "ねこ")
        cog.guild_settings.set_autojoin(gid, 20, 10)
        cog.guild_settings.add_ignored(gid, 5)

    await cog.on_guild_remove(cast(discord.Guild, SimpleNamespace(id=1)))

    assert cog.channel_store.get(1) == set()
    assert cog.word_dict.all(1) == {}
    assert cog.guild_settings.autojoin_all(1) == {}
    assert cog.guild_settings.ignored_all(1) == set()
    # 他のサーバーのデータは残る
    assert cog.channel_store.get(2) == {10}
    assert cog.word_dict.all(2) == {"cat": "ねこ"}
    assert cog.guild_settings.ignored_all(2) == {5}
    await cog.cog_unload()


# ---- R-15: kuroneko 形式の regex・null を取り込まない


def test_parse_dict_json_skips_regex_and_non_string() -> None:
    parsed = tts_mod.TTS._parse_dict_json({
        "kind": "com.kuroneko6423.kuronekottsbot.dictionary",
        "version": 1,
        "data": [
            {"before": "cat", "after": "ねこ", "regex": False},
            {"before": "c.t", "after": "x", "regex": True},
            {"before": None, "after": "x"},
            {"word": "dog", "reading": "いぬ"},
            "broken",
        ],
    })
    assert parsed == ({"cat": "ねこ", "dog": "いぬ"}, 3)
    assert tts_mod.TTS._parse_dict_json({"a": "b"}) == ({"a": "b"}, 0)
    assert tts_mod.TTS._parse_dict_json({"a": 1}) is None
    assert tts_mod.TTS._parse_dict_json([]) is None


def test_custom_url_labels() -> None:
    import text_filter

    labels = text_filter._parse_custom_url_labels("example.com=例のURL, bad, =x, foo.org=")
    assert len(labels) == 1
    pattern, label = labels[0]
    assert label == "例のURL"
    assert pattern.match("https://example.com/a")
    assert pattern.match("https://sub.example.com")
    assert not pattern.match("https://notexample.com/")
    assert not pattern.match("https://example.com.evil.net/")


# ---- R-8: Bot が外部から切断されたら状態を片付ける


async def test_bot_disconnect_resets_session(monkeypatch: pytest.MonkeyPatch) -> None:
    from bot import YomiageBot

    bot = SimpleNamespace(user_voice_store=SimpleNamespace(get=lambda _uid: 3), user=SimpleNamespace(id=999))
    cog = tts_mod.TTS(cast(YomiageBot, bot))
    reset: list[int] = []
    monkeypatch.setattr(cog, "_reset_guild_session", reset.append)

    def event(member_id: int, before: object, after: object):
        member = SimpleNamespace(id=member_id, bot=True, guild=SimpleNamespace(id=1))
        return (
            cast(discord.Member, member),
            cast(discord.VoiceState, SimpleNamespace(channel=before)),
            cast(discord.VoiceState, SimpleNamespace(channel=after)),
        )

    vc = SimpleNamespace(id=10)
    await cog.on_voice_state_update(*event(999, vc, SimpleNamespace(id=11)))  # 移動は対象外
    await cog.on_voice_state_update(*event(500, vc, None))  # 他の Bot は対象外
    assert reset == []
    await cog.on_voice_state_update(*event(999, vc, None))
    assert reset == [1]
    await cog.cog_unload()
