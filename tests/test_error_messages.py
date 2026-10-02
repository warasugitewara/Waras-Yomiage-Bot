from discord import app_commands
from discord.ext import commands

from bot import _user_error_message


def test_missing_permissions_message() -> None:
    for exc in (
        commands.MissingPermissions(["manage_guild"]),
        app_commands.MissingPermissions(["manage_guild"]),
    ):
        assert _user_error_message(exc) == "⛔ このコマンドを使うには「サーバー管理」権限が必要です。"


def test_no_private_message() -> None:
    for exc in (commands.NoPrivateMessage(), app_commands.NoPrivateMessage("x")):
        assert _user_error_message(exc) == "⛔ このコマンドはサーバー内でのみ使えます。"


def test_other_errors_are_not_reported_to_user() -> None:
    assert _user_error_message(commands.CommandNotFound()) is None
    assert _user_error_message(RuntimeError("boom")) is None
