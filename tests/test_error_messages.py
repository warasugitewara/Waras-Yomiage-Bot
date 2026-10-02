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


def test_argument_errors_are_reported() -> None:
    import inspect

    param = commands.Parameter("value", inspect.Parameter.POSITIONAL_OR_KEYWORD)
    msg = _user_error_message(commands.MissingRequiredArgument(param))
    assert msg is not None and "`value`" in msg
    assert _user_error_message(commands.BadArgument()) is not None
    assert _user_error_message(commands.MemberNotFound("x")) is not None
    attachment = commands.Parameter("file", inspect.Parameter.POSITIONAL_OR_KEYWORD)
    assert _user_error_message(commands.MissingRequiredAttachment(attachment)) == "⚠️ ファイルを添付して実行してください。"


async def test_group_usage_lists_subcommands() -> None:
    from types import SimpleNamespace
    from typing import cast

    from discord_helpers import send_group_usage

    @commands.group(name="dict")
    async def group(ctx: commands.Context) -> None: ...

    @group.command(name="add")
    async def add(ctx: commands.Context) -> None: ...

    @group.command(name="list")
    async def list_(ctx: commands.Context) -> None: ...

    sent: list[str] = []

    async def send(msg: str) -> None:
        sent.append(msg)

    ctx = SimpleNamespace(command=group, invoked_subcommand=None, prefix="!", send=send)
    await send_group_usage(cast(commands.Context, ctx))
    assert sent == ["使い方: `!dict <add|list>`（詳しくは `/help`）"]


async def test_group_usage_is_silent_when_subcommand_invoked() -> None:
    from types import SimpleNamespace
    from typing import cast

    from discord_helpers import send_group_usage

    sent: list[str] = []

    async def send(msg: str) -> None:
        sent.append(msg)

    ctx = SimpleNamespace(command=None, invoked_subcommand=object(), prefix="!", send=send)
    await send_group_usage(cast(commands.Context, ctx))
    assert sent == []
