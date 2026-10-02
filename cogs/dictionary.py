"""Dictionary Cog — サーバーごとの読み替え辞書（/dict）"""

import io
import json
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from discord_helpers import GuildOnlyCog, require_guild, send_chunks, send_group_usage, send_response

if TYPE_CHECKING:
    from bot import YomiageBot

# 読み替え辞書の上限（巨大入力による負荷・メモリ消費を防ぐ）
_DICT_IMPORT_MAX_BYTES = 1024 * 1024
_DICT_MAX_ENTRIES = 5000
_DICT_WORD_MAX_LEN = 50
_DICT_READING_MAX_LEN = 100

# /dict list をメッセージで表示する最大件数（超えたら JSON ファイルで返す）
_DICT_LIST_INLINE_MAX = 50


def _validate_dict_entry(word: str, reading: str) -> str | None:
    """辞書エントリを検証し、不正ならエラーメッセージを返す"""
    if not word.strip():
        return "⚠️ 空の単語は登録できません。"
    if len(word) > _DICT_WORD_MAX_LEN:
        return f"⚠️ 単語は {_DICT_WORD_MAX_LEN} 文字以内で指定してください。"
    if len(reading) > _DICT_READING_MAX_LEN:
        return f"⚠️ 読みは {_DICT_READING_MAX_LEN} 文字以内で指定してください。"
    return None


def _dict_json_file(guild_id: int, d: dict[str, str]) -> discord.File:
    """辞書を本Bot形式の JSON ファイルにする（export / 件数の多い list で共用）"""
    payload = {
        "version": 1,
        "data": [{"word": w, "reading": r} for w, r in d.items()],
    }
    buf = io.BytesIO(json.dumps(payload, ensure_ascii=False, indent=2).encode())
    return discord.File(buf, filename=f"dict_{guild_id}.json")


class Dictionary(GuildOnlyCog):
    def __init__(self, bot: "YomiageBot"):
        self.bot = bot
        self.word_dict = bot.word_dict

    # ------------------------------------------------------------------ #
    # dict サブコマンドグループ
    # ------------------------------------------------------------------ #

    @commands.hybrid_group(name="dict", description="読み替え辞書の管理")
    async def dict_group(self, ctx: commands.Context):
        await send_group_usage(ctx)

    @dict_group.command(name="add", description="読み替え辞書に単語を追加します")
    @app_commands.describe(word="元の単語", reading="読み替え後のテキスト")
    async def dict_add_prefix(self, ctx: commands.Context, word: str, reading: str):
        await self._dict_add(ctx, word, reading)

    async def _dict_add(self, ctx_or_inter, word: str, reading: str):
        guild_id = ctx_or_inter.guild.id
        error = _validate_dict_entry(word, reading)
        current = self.word_dict.all(guild_id)
        if error is None and word not in current and len(current) >= _DICT_MAX_ENTRIES:
            error = f"⚠️ 辞書の登録数が上限（{_DICT_MAX_ENTRIES}件）に達しています。"
        if error:
            await send_response(ctx_or_inter, error, ephemeral=True)
            return
        self.word_dict.add(guild_id, word, reading)
        await send_response(ctx_or_inter, f"📖 `{word}` → `{reading}` を辞書に追加しました。")

    @dict_group.command(name="remove", description="読み替え辞書から単語を削除します")
    @app_commands.describe(word="削除する単語")
    async def dict_remove_prefix(self, ctx: commands.Context, word: str):
        removed = self.word_dict.remove(require_guild(ctx).id, word)
        await ctx.send(f"🗑️ `{word}` を削除しました。" if removed else f"`{word}` は辞書にありません。")

    @dict_group.command(name="list", description="読み替え辞書の一覧を表示します")
    async def dict_list_prefix(self, ctx: commands.Context):
        await self._dict_list(ctx)

    async def _dict_list(self, ctx_or_inter):
        guild_id = ctx_or_inter.guild.id
        d = self.word_dict.all(guild_id)
        if not d:
            await send_response(ctx_or_inter, "辞書は空です。", ephemeral=True)
            return
        # 件数が多いとチャンネルが連投で埋まるため、JSON ファイルにまとめて本人にだけ返す
        if len(d) > _DICT_LIST_INLINE_MAX:
            msg = f"📖 読み替え辞書（{len(d)}件）は件数が多いためファイルで送ります。"
            file = _dict_json_file(guild_id, d)
            if isinstance(ctx_or_inter, discord.Interaction):
                await ctx_or_inter.response.send_message(msg, file=file, ephemeral=True)
            else:
                await ctx_or_inter.send(msg, file=file, ephemeral=True)
            return
        lines = "\n".join(f"• `{w}` → `{r}`" for w, r in d.items())
        await send_chunks(ctx_or_inter, f"📖 読み替え辞書 ({len(d)}件):\n{lines}", ephemeral=True)

    @dict_group.command(name="export", description="辞書をJSONファイルとしてエクスポートします")
    async def dict_export_prefix(self, ctx: commands.Context):
        await self._dict_export(ctx)

    async def _dict_export(self, ctx_or_inter):
        guild_id = ctx_or_inter.guild.id
        d = self.word_dict.export_dict(guild_id)
        file = _dict_json_file(guild_id, d)
        if isinstance(ctx_or_inter, discord.Interaction):
            await ctx_or_inter.response.send_message(
                f"📤 辞書をエクスポートしました（{len(d)}件）", file=file
            )
        else:
            await ctx_or_inter.send(f"📤 辞書をエクスポートしました（{len(d)}件）", file=file)

    @dict_group.command(name="import", description="JSONファイルから辞書をインポートします（サーバー管理権限が必要）")
    @app_commands.describe(
        file="インポートするJSONファイル",
        replace="True で既存辞書を全置換（デフォルト: False でマージ）",
    )
    @commands.has_permissions(manage_guild=True)
    async def dict_import_prefix(
        self,
        ctx: commands.Context,
        file: discord.Attachment,
        replace: bool = False,
    ):
        await ctx.defer()
        await self._dict_import(ctx, file, replace)

    async def _dict_import(self, ctx_or_inter, attachment: discord.Attachment, replace: bool):
        if not attachment.filename.endswith(".json"):
            await send_response(ctx_or_inter, "⚠️ `.json` ファイルのみ対応しています。")
            return
        # 読み込み前にサイズを検査（巨大ファイルをメモリへ展開しない）
        if attachment.size > _DICT_IMPORT_MAX_BYTES:
            await send_response(
                ctx_or_inter,
                f"⚠️ ファイルサイズが上限（{_DICT_IMPORT_MAX_BYTES // 1024}KB）を超えています。",
            )
            return
        try:
            raw_bytes = await attachment.read()
            data = json.loads(raw_bytes.decode("utf-8"))
        except Exception:
            await send_response(ctx_or_inter, "⚠️ JSONの読み込みに失敗しました。ファイルが正しいか確認してください。")
            return

        parsed = self._parse_dict_json(data)
        if parsed is None:
            await send_response(ctx_or_inter, "⚠️ サポートされていないJSONフォーマットです。")
            return
        entries, skipped = parsed

        # 空単語は読み上げに影響しないため黙ってスキップする
        entries = {w: r for w, r in entries.items() if w.strip()}
        guild_id = ctx_or_inter.guild.id
        error = self._check_dict_import(
            entries, {} if replace else self.word_dict.all(guild_id)
        )
        if error:
            await send_response(ctx_or_inter, f"{error}\nインポートは行われませんでした。")
            return

        count = self.word_dict.import_dict(guild_id, entries, replace=replace)
        mode = "全置換" if replace else "マージ"
        msg = f"📥 辞書を{mode}でインポートしました（{count}件）。"
        if skipped:
            msg += f"\n⚠️ 正規表現のエントリや値が文字列でないエントリ {skipped}件は取り込みませんでした。"
        await send_response(ctx_or_inter, msg)

    @staticmethod
    def _check_dict_import(entries: dict[str, str], current: dict[str, str]) -> str | None:
        """インポート内容を検証する。1件でも不正なら全体を拒否するためエラーを返す"""
        for word, reading in entries.items():
            error = _validate_dict_entry(word, reading)
            if error:
                return f"{error}（`{word[:_DICT_WORD_MAX_LEN]}`）"
        total = len(current.keys() | entries.keys())
        if total > _DICT_MAX_ENTRIES:
            return f"⚠️ 登録数が上限（{_DICT_MAX_ENTRIES}件）を超えます（インポート後 {total}件）。"
        return None

    @staticmethod
    def _parse_dict_json(data: object) -> tuple[dict[str, str], int] | None:
        """各種フォーマットのJSONを ({word: reading}, 取り込めなかった件数) に変換する。

        対応フォーマット:
        - 本Bot形式: {"version":1, "data":[{"word":"...","reading":"..."},...]}
        - kuroneko形式: {"kind":"...","version":1,"data":[{"before":"...","after":"...","regex":...},...]}
        - シンプル形式: {"word":"reading",...}

        kuroneko形式の regex: true は正規表現として解釈できないため取り込まない
        （文字列として取り込むと意味が黙って変わる）。値が文字列でないエントリも取り込まない。
        """
        if not isinstance(data, dict):
            return None

        if "data" in data and isinstance(data["data"], list):
            result: dict[str, str] = {}
            skipped = 0
            for item in data["data"]:
                if not isinstance(item, dict):
                    skipped += 1
                    continue
                if "before" in item and "after" in item:
                    # kuroneko形式
                    word, reading = item["before"], item["after"]
                    if item.get("regex") is True:
                        skipped += 1
                        continue
                elif "word" in item and "reading" in item:
                    # 本Bot形式
                    word, reading = item["word"], item["reading"]
                else:
                    skipped += 1
                    continue
                if not (isinstance(word, str) and isinstance(reading, str)):
                    skipped += 1
                    continue
                result[word] = reading
            return result, skipped

        # シンプルフラット形式 {"word": "reading"}
        if all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
            return dict(data), 0

        return None


async def setup(bot: "YomiageBot"):
    await bot.add_cog(Dictionary(bot))
