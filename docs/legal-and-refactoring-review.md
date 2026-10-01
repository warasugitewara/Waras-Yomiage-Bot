# リーガル / リファクタリング レビュー報告書

- **対象リポジトリ**: `warasugitewara/Waras-Yomiage-Bot`
- **対象コミット**: `e14ace6` (`feat: 発言者名の読み上げ（/readname）を追加`)
- **レビュー日**: 2026-10-01
- **対象範囲**: Python 22ファイル（本体16 + テスト6）/ 約3,500行、README・`.env.example`・CI 定義
- **きっかけ**: 姉妹プロジェクト `JP-MuseHeart-MusicBot` のレビュー（`docs/legal-and-refactoring-review.md`）で問題が見つかったため、同じ観点で本 Bot を点検した

## 調査方法と検証状況

| 項目 | 方法 | 結果 |
|---|---|---|
| テスト | `uv sync --locked` → `uv run pytest -q` | **46 passed** |
| 型検査 | `uvx pyright@1.1.414 .`（CI と同じ版） | **0 errors** |
| Lint | `uvx ruff check --select E,F,W,B,UP,SIM,ASYNC` | E501（行長）148件を除くと **10件**（後述 R-13） |
| 依存ライブラリのライセンス | `.venv` に入った全パッケージの METADATA と PyPI JSON API で確認 | コピーレフト **0件**（L-6） |
| 秘密情報の混入 | `git fetch --unshallow` で**全103コミット**を取得し、Bot トークン形式・Webhook URL・Uptime Kuma の push トークン・`.env` / `data/*.json` のコミット有無を正規表現で走査 | **検出0件**（プレースホルダ `xxxxxxxxxxxx` のみ） |
| バグ候補 | 再現スクリプトを作って実際に動かす / 使用中の discord.py 2.7.1 のソースを読む | 各項目に「再現済み」「ソース確認」「未検証」を明記 |
| 外部規約 | 下表のとおり | — |

**外部情報の取得元と限界**

| 情報 | 取得元 | 状況 |
|---|---|---|
| VOICEVOX ソフトウェア利用規約・Q&A・キャラクター別の規約概要 | VOICEVOX 公式サイトのソース（GitHub `VOICEVOX/voicevox_blog`、最新コミット `934acc9` / 2026-09-07） | ✅ 原文を確認 |
| discord.py の DAVE 対応 | `Rapptz/discord.py` の `docs/whats_new.rst`（master） | ✅ 確認 |
| Discord の DAVE 必須化の時期 | Discord 公式ブログおよび報道（Web 検索） | ✅ 確認 |
| 特権インテントの申請基準 | GitHub `discord/discord-api-docs`（最新コミット `86f0a46` / 2026-09-30） | ✅ 確認 |
| **各キャラクターの利用規約の本文**（zunko.jp ほか） | — | ⚠️ **この環境のネットワーク制限で取得できず**。VOICEVOX 公式サイトにある概要で代用した |
| **Discord Developer Policy / Developer Terms の本文** | — | ⚠️ **同上で取得できず**（`discord-api-docs` 側は外部リンクだけのスタブ） |

> ⚠️ 取得できなかった一次資料に関わる記述には「**要原典確認**」と付けています。

---

# 第1部: リーガル（ライセンス・法務）レビュー

## 総評

MuseHeart で問題になった **GPL / AGPL の混入に相当する問題はありません**。本 Bot は MIT で、依存ライブラリもすべて許容型（permissive）のライセンスです。VOICEVOX ENGINE も FFmpeg も同梱・再配布していません。

README の「クレジット・利用規約」「データの取り扱い」の節は、すでにかなり整っています。それでも、**VOICEVOX のキャラクター別規約との細かいズレ**と、**データ削除の抜け**が見つかりました。

| ID | 重要度 | 概要 |
|---|---|---|
| L-1 | 中 | 自動生成されるクレジット表記が、一部キャラクターで指定の形式と一致しない |
| L-2 | 中 | VC で音声を聞いている人に対して、クレジットが表示されていない |
| L-3 | 低〜中（運用形態による） | 非商用限定や、法人利用に事前確認が必要なキャラクターも選べてしまう |
| L-4 | 低〜中 | プライバシー: サーバーから退出してもデータが残る。README の記述と実装に一部ズレがある |
| L-5 | 情報 | Message Content Intent の申請基準が変わった |
| L-6 | ✅ 問題なし | 依存ライブラリのライセンス |
| L-7 | ✅ 問題なし | LICENCE・著作権表示、VOICEVOX ENGINE / FFmpeg の扱い |
| L-8 | 低 | `.env.example` に実在形式のユーザー ID と個人ドメインが入っている |
| 付記 | — | MuseHeart 報告書 L-8 の記述（「個人識別符号」）の訂正 |

---

## L-1 【中】自動生成されるクレジット表記が、一部キャラクターで指定の形式と一致しない

`cogs/tts.py:513-518` の `_resolve_credit()` は、どのキャラクターでも一律に
`f"VOICEVOX:{entry[0]}"`（`entry[0]` は ENGINE の `/speakers` が返すキャラクター名）を
クレジットとして表示します（`/myvoice set`・`/myvoice info`）。

VOICEVOX 公式サイトのキャラクター別規約概要（`src/assets/library-term-intro-markdowns/*.md`）には、
次の 4 キャラクターについて、**キャラクター名だけではない表記**が指定されています。

| キャラクター | 公式サイトに書かれた指定の表記 | Bot が生成する表記（※） |
|---|---|---|
| もち子さん | `VOICEVOX:もち子(cv 明日葉よもぎ)` | `VOICEVOX:もち子さん` |
| Voidoll | `VOICEVOX:Voidoll(CV:丹下桜)` | `VOICEVOX:Voidoll` |
| ユーレイちゃん | `VOICEVOX:ユーレイちゃん(CV:神崎零)` | `VOICEVOX:ユーレイちゃん` |
| 里石ユカ | `VOICEVOX:里石ユカ（つぼみ）` | `VOICEVOX:里石ユカ` |

※ 公式サイトの `characterInfos/*.ts` の `name` と README のスピーカー表は、どちらも「もち子さん」「Voidoll」「ユーレイちゃん」となっています。
ENGINE の `/speakers` も同じ名前を返すと仮定した場合の表記です。**実機の ENGINE で返る名前はこのレビューでは確認していません。**

**推奨対応**

- `{キャラクター名: クレジット表記}` の上書き表を持ち、該当するキャラクターだけ差し替える（数行）。
- 指定の表記は今後も変わり得るので、上書き表に出典 URL（各キャラクターの規約ページ）をコメントで残す。
  キャラクターごとの規約ページの URL は、公式サイトの `characterInfos/*.ts` にある `policyUrl` で確認できます。**要原典確認。**

---

## L-2 【中】VC で音声を聞いている人に対して、クレジットが表示されていない

VOICEVOX のソフトウェア利用規約（`src/pages/term.md`）:

> ご利用の際は VOICEVOX を利用したことがわかるクレジット表記が必要です。
>
> 3. 作成された音声の利用を他者に許諾する際は、当該他者に対し本許諾内容の 2 及び 3 の遵守を義務付けてください

VOICEVOX Q&A（`src/pages/qa/index.md`）:

> Q. スピーカーでの音声案内など、機械で音声を流したい場合のクレジット記載はどうすれば良いですか？
> 音声の最初や最後に音声クレジットを挿入するか、その機械や周辺にてクレジットを表記してください。
> キャラクターの利用規約に案内がある場合はそちらを優先してください。

**現状**

- 音声を選んだ本人には、`/myvoice set` と `/myvoice info` でクレジットが表示される。
- `/about` に出るのは「VOICEVOX:ずんだもん ほか各キャラクター」だけ。
- ところが **VC で実際に音声を聞いている他のメンバー**は、どのキャラクターの声かを、Bot の周辺（プロフィール・読み上げ先チャンネルなど）で確認できない。
- 規約 3 項の「利用者への遵守の義務付け」については、README がサーバー管理者に「利用者にも求めてください」と書いている。しかし **Bot の中には利用者向けの案内がない**。

**推奨対応**（解釈を含みます。安全側に倒した提案です）

1. Bot の Discord プロフィール（About Me）に「音声: VOICEVOX（各キャラクター）/ クレジットは `/about` 参照」と書くよう、README で運用者に案内する（コード変更なし）。
2. `/about` で、**利用中のスピーカーのクレジット一覧**（`users.json` に入っている speaker_id とデフォルト話者から作る）を表示する。
3. `/join` で接続したときや `/help` に、「音声は VOICEVOX と各キャラクターの利用規約に従ってご利用ください」という一文を入れる。

---

## L-3 【低〜中 / 運用形態による】非商用限定や、法人利用に事前確認が必要なキャラクターも選べてしまう

`/myvoice set` は ENGINE が返す**すべての**スタイル ID を受け付けます（`cogs/tts.py:644-663`）。
公式サイトの概要によると、キャラクターごとに次の条件があります（**要原典確認**）。

| 条件 | キャラクター |
|---|---|
| 非商用のみ（同人利用や配信による収入は可） | No.7、ユーレイちゃん |
| 企業が関わる利用は事前確認が必要 | 青山龍星、後鬼、もち子さん |
| 法人による利用は個別に問い合わせ | Voidoll |
| 商用利用は個別に問い合わせ | ぞん子 |

個人が非営利で運用している現状では、どれにも該当しないと考えられます。
ただし、**企業のサーバーへの導入**や**有償での運用**をすると、運用者がこれらの条件を満たす必要が出てきます。

**推奨対応**

- `.env` に `ALLOWED_SPEAKERS` / `DENIED_SPEAKERS`（スピーカー ID のリスト）を追加し、運用者が選べる話者を絞れるようにする。
- README の「クレジット・利用規約」に「法人・商用で運用する場合はキャラクターごとの条件を確認すること」と追記する。

---

## L-4 【低〜中】プライバシー: サーバーから退出してもデータが残る。README の記述と実装に一部ズレがある

README の「データの取り扱い」は、保存先・内容・削除方法を表にまとめていて、MuseHeart（プライバシー文書なし）よりずっと良い状態です。
`json_store.save_json()` は `tempfile.mkstemp` を使うので、**`data/*.json` とバックアップは `0600` で作られます**（実測。共有ホストでも他のユーザーからは読めない）。
Bot は `self_deaf=True` で VC に参加し、音声を受信しません。これもプライバシー面で良い設計です。

**見つかった不足**

| # | 内容 | 根拠 |
|---|---|---|
| (a) | **Bot がサーバーから退出・キックされても、そのサーバーのデータ（読み上げチャンネル・辞書・自動参加・除外ユーザー ID）が消えずに残る** | `on_guild_remove` のハンドラが存在しない（grep で確認） |
| (b) | `users.json` のユーザー ID は、本人が `/myvoice reset` しない限り消えない（Discord アカウントを削除しても残る） | `user_store.py` |
| (c) | README には Webhook で「サーバー名・ユーザー名・コマンド名」が送られるとある。実際には **guild_id / channel_id とトレースバック**も送られる | `cogs/tts.py:318-321, 1222-1225`、`webhook_logger.py:85-91` |
| (d) | README の「第三者へ提供しません」の記述。`VOICEVOX_URL` を別ホスト（README で触れている GPU VM など）に向けると、**メッセージ本文が平文 HTTP でネットワーク上を流れる**ことに触れていない | `voicevox.py:94-98` |

**Discord 側の要件**（**要原典確認**。Developer Policy / Developer Terms の本文はこの環境から取得できませんでした）

- 公開 Bot として運用する場合、Discord はアプリのプライバシーポリシーの掲示を求めています（アプリ設定の `privacy_policy_url` 欄。収益化の申請では掲示が要件として明記されています。出典: `discord-api-docs` `developers/monetization/enabling-monetization.mdx`）。
- 特権インテントの申請ガイドでは、データを保存する場合に「なぜ必要か、保持ポリシー、セキュリティ対策」を説明するよう求めています（`getting-started-with-privileged-intent-review.mdx`）。

**推奨対応**

1. `on_guild_remove` で、そのサーバーの `channel_store` / `word_dict` / `guild_settings` を削除する（10行程度）。
2. README のデータ表に「Bot がサーバーから退出したときの扱い」と「保持期間」を追記し、Webhook の送信項目を実装と合わせる。
3. `VOICEVOX_URL` は同一ホストか、信頼できるプライベートネットワークに限ること、と README に一行追記する。
4. 公開運用する場合に備えて `PRIVACY.md` のひな形を用意する（README の表をほぼ流用できる）。

---

## L-5 【情報】Message Content Intent の申請基準が変わった

`discord-api-docs`（2026-09-30 時点）の `getting-started-with-privileged-intent-review.mdx`:

> Previously, apps in fewer than 100 servers could access Privileged Intents by toggling them on in the Developer Portal, and apps in 100+ servers needed to apply for access. That threshold is now based on the number of unique users who can see your app across all the servers it's in. If that number exceeds 10,000, your app needs to apply for Privileged Intent access.

本 Bot は読み上げのために Message Content Intent を**必ず**必要とします（`bot.py:25`）。
小さなサーバー数台でも、**合計の見えるユーザー数が 1 万人を超えると申請が必要**になります。
申請では「具体的な用途」と「データの扱い（保存するのか、メモリ上で処理して捨てるのか）」を説明する必要があります。
README の「メッセージ本文はディスクに保存しません」の記述は、そのまま申請理由に使えます。

---

## L-6 【✅ 問題なし】依存ライブラリのライセンス

`uv.lock` の全 26 パッケージを確認しました（うち `audioop-lts`（Python 3.13 以上のみ）と `colorama`（Windows のみ）は PyPI JSON で確認）。

| ライセンス | パッケージ |
|---|---|
| MIT | discord.py, davey, attrs, iniconfig, pluggy, pytest |
| MIT-0 | cffi |
| Apache-2.0 | PyNaCl, aiosignal, frozenlist, multidict, propcache, yarl, pytest-asyncio |
| Apache-2.0 AND MIT | aiohttp |
| Apache-2.0 OR BSD-2-Clause | packaging |
| BSD-3-Clause | psutil, python-dotenv, idna, pycparser, colorama |
| BSD-2-Clause | Pygments |
| PSF-2.0 | aiohappyeyeballs, typing-extensions, audioop-lts |

GPL / LGPL / AGPL は **0件** です。依存は `pip` / `uv` で各自インストールする形で、
本リポジトリが同梱・再配布するものはないため、Apache-2.0 の NOTICE を同梱する義務も生じません。

---

## L-7 【✅ 問題なし】LICENCE・著作権表示、VOICEVOX ENGINE / FFmpeg の扱い

- `LICENCE` は MIT の全文で、著作権表示 `Copyright (c) 2026 .warasugi` があります（MuseHeart の L-3 に相当する問題はない）。
  最初のコミットは 2026-04-30 なので、年も合っています。`pyproject.toml` の `license = "MIT"` とも一致しています。
- VOICEVOX ENGINE は同梱していません。README の手順も公式 Releases からの取得なので、
  VOICEVOX 規約の禁止事項「本ソフトウェアの全てまたは一部を無断で再配布すること」には当たりません。
- FFmpeg は外部プロセスとして `ffmpeg` コマンドを呼び出すだけで（`cogs/tts.py:99-107`）、同梱もリンクもしていないため、ライセンスの問題は生じません。
- AI 支援のクレジット: README に MuseHeart の L-11(c) のような「@claude (Anthropic)」の記載はありません。コミットの `Co-Authored-By` だけで、誤帰属はありません。

---

## L-8 【低】`.env.example` に実在形式のユーザー ID と個人ドメインが入っている

- `.env.example:30` `# OWNER_IDS=811515262238064640`: 他の例（`123456789012345678` など）と違い、実在する形式の Discord ユーザー ID です。
  Discord のユーザー ID は秘密情報ではありません。しかし、これをそのままコピーした運用者が**第三者にオーナー権限を与えてしまう**事故の元になります。
- `.env.example:41` `status.warasugi.com`、`text_filter.py:12` の `warasugi.com` → 「わらすぎのURL」: 個人のドメインが汎用の設定例やコードに入っています（法的な問題ではなく、フォークした人にとってのノイズ。R-15 参照）。

**推奨対応**: `OWNER_IDS` の例を `123456789012345678` に、Uptime Kuma の例を `https://your-uptime-kuma/...` に置き換える。

---

## 付記: MuseHeart 報告書 L-8 の訂正

MuseHeart の報告書の L-8 には「日本の個人情報保護法（APPI）上、Discord ユーザーIDは個人識別符号に該当し得ます」とあります。
しかし、**個人情報保護法の「個人識別符号」（法2条2項）は、政令で定められたもの（DNA・顔・指紋などの身体的特徴のデータと、旅券番号・マイナンバーなどの公的な番号）に限られます**。
民間サービスが割り当てる ID はこれに当たりません。

Discord ユーザー ID は、**他の情報と容易に照合して特定の個人を識別できる場合に「個人情報」に当たり得る**、というのが正しい整理です。
結論（データを適切に扱い、削除の手段を用意すべき）は変わりませんが、用語は訂正しておくのが望ましいです。

---

# 第2部: リファクタリング / コード品質レビュー

## 総評

テスト 46 件、Pyright のエラー 0、CI あり、JSON はアトミック書き込みと世代バックアップ付き、Uptime Kuma のトークンをログに出さない。
**基礎体力は MuseHeart（テスト・CI なし、裸の except 365 箇所）より大幅に良い状態**です。

一方で、権限チェックの抜け（R-1）、データ消失バグ（R-2）、メンション注入（R-3）、イベントループの占有（R-4）は、**確定している、または経路を確認済みの問題**です。

| ID | 重要度 | 分類 | 概要 | 検証 |
|---|---|---|---|---|
| R-1 | **高** | セキュリティ | `/listen add` で、実行者が閲覧できない非公開チャンネルを読み上げ対象にできる | ソース確認 |
| R-2 | **高** | バグ | `/owner import_users` が `speaker_id: true` を受け入れ、全ユーザー設定が消える | **再現済み** |
| R-3 | 中 | セキュリティ | `allowed_mentions` 未設定 + バッククォート未エスケープ → `@everyone` 注入 | 経路のみ確認 |
| R-4 | 中 | 性能 / DoS | 辞書 5000 件でメッセージ 1 件あたり最大 184ms イベントループを止める。辞書の編集に権限不要 | **実測** |
| R-5 | 中 | UX バグ | 権限不足・引数ミスに無反応。スラッシュでは「応答しませんでした」 | ソース確認 |
| R-6 | 低 | UX バグ | `!myvoice` などをサブコマンドなしで打つと何も返らない | ソース確認 |
| R-7 | 低 | 運用 | `/dict list` が全件を公開チャンネルに数十通に分けて投稿する | コード確認 |
| R-8 | 低 | バグ | Bot が外部から VC を切断されたとき、状態が片付かない | コード確認 |
| R-9 | 中 | 依存 | discord.py の下限 `>=2.3.0` は DAVE 必須化後は不正確 | 一次資料確認 |
| R-10 | 低 | ドキュメント | README の systemd 節が Proxmox 節と矛盾し、root で実行する手順になっている | 確認 |
| R-11 | 中 | 構造 | `cogs/tts.py` 1,295 行。prefix と slash を二重に定義（19 + 19） | ast 集計 |
| R-12 | 低 | 構造 | 環境変数の読み込みが散らばっていて、検証もない | grep |
| R-13 | 低 | 品質 | 未使用コード・lint 10 件 | ruff |
| R-14 | 低 | 依存 | `requirements.txt` と `pyproject.toml` / `uv.lock` の二重管理 | 確認 |
| R-15 | 低 | 汎用性 | 個人ドメインのハードコード、kuroneko 形式の `regex` フラグを無視 | 確認 |
| R-16 | 低 | CI | Actions をタグで参照していて、SHA で固定していない | 確認 |
| R-17 | 低 | ドキュメント | README / `/help` と実装のズレ | 確認 |

---

## 確定バグ・セキュリティ

### R-1 【高】`/listen add` で、実行者が閲覧できない非公開チャンネルを読み上げ対象にできる

`cogs/tts.py:754-770`:

```python
@listen_group.command(name="add")
async def listen_add_prefix(self, ctx, channel: discord.TextChannel | None = None):
    await self._listen_add(ctx, channel or ctx.channel)
...
async def _listen_add(self, ctx_or_inter, channel):
    ...
    added = self.channel_store.add(guild.id, channel.id)   # 権限チェックなし
```

- コマンドに**権限チェックがありません**（`@has_permissions` なし）。
- discord.py 2.7.1 の `TextChannelConverter`（`ext/commands/converter.py:470-498`）は `guild.get_channel(channel_id)` で ID からチャンネルを引くだけで、**実行者がそのチャンネルを閲覧できるかは確認しません**。

**攻撃シナリオ**: 一般メンバーが、自分には見えない運営用チャンネルの ID（開発者モードや過去のリンクから取得できる）を `!listen add 123…` に渡します。
Bot がそのチャンネルを読める権限を持っていれば、**運営チャンネルの投稿が、そのメンバーのいる VC で読み上げられます**（情報漏えい）。

スラッシュ版で Discord 側がチャンネルの選択肢を権限でしぼるかどうかは、このレビューでは検証していません。prefix 版だけで成立します。

**推奨対応**（数行）: `_listen_add` で次の 2 点を確認し、満たさなければ拒否する。

- `channel.permissions_for(実行者).read_messages`
- （望ましくは）VC にいるメンバーがそのチャンネルを閲覧できること

`/listen remove` も、他人が追加したチャンネルを外せるため、`manage_channels` 程度の権限を付けるか検討してください。

---

### R-2 【高】`/owner import_users` が `speaker_id: true` を受け入れ、全ユーザー設定が消える

`cogs/owner.py:154` の検証が `isinstance(spk, int)` だけになっています。Python では `bool` は `int` のサブクラスなので、`true` が通ります。
一方、読み込み側の `user_store._validate_users()` は bool を拒否します。**書き込みと読み込みで検証が食い違っている**ことが原因です。

**再現**（このレビューで実行。一時ディレクトリで実施）:

```
parsed: {'333': True}
file: {  "111": 3,  "222": 46,  "333": true}
[STORE] スキーマ不一致のためスキップ: users.json
reload after import: {'111': 3, '222': 46}       ← 再起動するとインポート分が消える
[STORE] スキーマ不一致のためスキップ: users.json
[STORE] スキーマ不一致のためスキップ: users.bak1
[STORE] スキーマ不一致のためスキップ: users.bak2
[STORE] スキーマ不一致のためスキップ: users.bak3
reload after 3 more saves: {}                     ← バックアップも汚染され全件消失
```

メモリ上には `True` が残ったまま、`/myvoice set` のたびに `users.json` 全体が書き直されます。
そのため、**3 回保存されると世代バックアップ 3 つがすべて不正な内容になり、次に起動したとき全ユーザーのボイス設定が空になります**。

あわせて、`_import_users` には辞書インポート（1MB）のような**サイズ上限がない**ことと、speaker_id が実在するかの検証がないことも見つかりました。

**推奨対応**:

- `_parse_users_json` を `user_store._validate_users` と同じ判定（`isinstance(v, int) and not isinstance(v, bool)`）にそろえる。できれば検証関数を 1 つにまとめる。
- サイズ上限を付ける。
- 回帰テストを 1 件追加する。

---

### R-3 【中】`allowed_mentions` 未設定 + バッククォート未エスケープ → `@everyone` 注入

`bot.py` では `allowed_mentions` を設定していません（grep で 0 件）。
この場合、Bot が送るメッセージの本文に `@everyone` が含まれ、**Bot にそのサーバーで「@everyone へのメンション」権限があれば、全員に通知が飛びます**。

ユーザーの入力を、エスケープせずに `` ` `` で囲んでそのまま返している箇所があります。

| 箇所 | 入力元 |
|---|---|
| `cogs/tts.py:836` `` f"📖 `{word}` → `{reading}` を辞書に追加しました。" `` | `/dict add`（**権限不要**） |
| `cogs/tts.py:841, 848` | `/dict remove` |
| `cogs/tts.py:959` | `/dict import` のエラー |
| `cogs/utility.py:172` `` f"⚠️ `{command}` というコマンドは見つかりません。" `` | `!help`（prefix 版は ephemeral にならない） |

例えば `` !help x`@everyone `` と送ると、Bot の返信は `` ⚠️ `x`@everyone` というコマンドは… `` になります。
入力に含めたバッククォートでインラインコードが閉じるため、`@everyone` が**コードの外**に出ます。

**検証範囲**: コード上の経路は確認しました。実際の Discord サーバーで通知が飛ぶかは試していません（Bot の権限設定に依存）。

**推奨対応**（1 行）: `YomiageBot.__init__` の `super().__init__()` に
`allowed_mentions=discord.AllowedMentions.none()` を渡す。
`/ignore` の返信の `<@id>` は表示用なので、通知が飛ばなくても困りません。

---

### R-4 【中】辞書 5000 件で、メッセージ 1 件あたり最大 184ms イベントループを止める。辞書の編集に権限は不要

`text_filter.filter_message()` は、すべての単語を `|` でつないだ 1 本の正規表現を、**長文カット（`max_length`）より前に、メッセージ全体へ**適用します。
Python の `re` はこの種の交替（`A|B|C|…`）を最適化しないので、コストは「メッセージ長 × 単語数」に比例します。

**実測**（このレビューの環境、`filter_message` を 5 回実行した平均）:

| 辞書の件数 | 2,000 文字（ASCII） | 2,000 文字（日本語） | 4,000 文字（日本語） |
|---|---|---|---|
| 100 | 1.2 ms | 1.3 ms | 2.7 ms |
| 1,000 | 13.4 ms | 13.1 ms | 26.3 ms |
| 5,000（上限） | **85.6 ms** | **90.7 ms** | **184.4 ms** |

- `/dict add` と `/dict import` には**権限チェックがない**ので、一般メンバーでも 5,000 件を登録できる。
- 正規表現の処理中は GIL を握ったままになる。そのため、discord.py の音声送信スレッドも止まり、**読み上げの音が途切れる**原因になり得る。
- 他にも、メッセージごとに `word_dict.all()` で辞書をコピーし、`frozenset()` を作り直している（`cogs/tts.py:1253`、`text_filter.py:143`）。

**推奨対応**:

1. 辞書を適用する前に、`max_length` の数倍（例: 4 倍）で入力を切り詰める。出力はどうせ `max_length` で切られるので、挙動は変わらない。4,000 文字が 400 文字になれば、計算量は約 1/10。
2. `/dict import`（特に `replace=True`）と `/dict remove` に `manage_guild` などの権限を付けるか、運用者が設定で選べるようにする。
3. コンパイル済みの正規表現を `WordDict` 側でギルドごとに持ち、辞書を変更したときだけ作り直す。

---

### R-5 【中】権限不足・引数ミスに無反応。スラッシュでは「アプリケーションが応答しませんでした」

`bot.py:125-150` の `on_command_error` と、`bot.py:152-178` の `_on_tree_error` は、`MissingPermissions` / `CheckFailure` / `BadArgument` / `MissingRequiredArgument` などを**黙って `return`** します。

- prefix の場合: 権限のない人が `!autojoin add …` を打つ、あるいは `!speed abc` と打つと、**何も返らない**。
- スラッシュの場合: 応答（`response`）をしないまま終わるため、Discord のクライアントに **「アプリケーションが応答しませんでした」** と表示される。
  pure な app command（`/autojoin`・`/ignore`）は `tree.on_error` を通ります。
  hybrid command（`/readname`・`/reload_speakers`）は、discord.py 2.7.1 の `ext/commands/hybrid.py:455-480` で `on_command_error` に回されます。どちらも同じく無反応です。
- Webhook に通知するべき「本当のエラー」の場合でも、スラッシュ版ではユーザーへの応答がありません。

**推奨対応**: 無視しているエラーのそれぞれに、短い ephemeral の返信（「⛔ サーバー管理権限が必要です」など）を返す。
`interaction.response.is_done()` を見て `followup` に切り替える処理は、既存の `discord_helpers.send_response` を使えます。

---

### R-6 【低】`!myvoice` などをサブコマンドなしで打つと何も返らない

`bot.py:29` で `help_command=None` にしています。
discord.py 2.7.1 の `Context.send_help()`（`ext/commands/context.py:551-` → `cmd = bot.help_command` が `None` なら `return None`）は、**この場合何もしません**。

そのため、`ctx.send_help(ctx.command)` を呼んでいる 6 つのグループ（`myvoice` / `listen` / `dict` / `autojoin` / `ignore` / `owner`）は、サブコマンドなしで打つと無反応になります。

**推奨対応**: `_HELP_DATA` から該当カテゴリを返すか、「`/help <コマンド>` を参照」と返す。

---

### R-7 【低】`/dict list` が全件を公開チャンネルに数十通に分けて投稿する

`_dict_list` は全件を `_send_chunks()` で 1,900 文字ずつに分けて送ります。ephemeral にはしていません。
辞書が上限の 5,000 件なら、**数十通の連投**になります（1 行あたりの長さによる）。権限は不要なので、荒らしの踏み台やレート制限の原因になります。

**推奨対応**: 一定件数を超えたら `/dict export` と同じく JSON ファイルを添付する。または ephemeral にする。

---

### R-8 【低】Bot が外部から VC を切断されたとき、状態が片付かない

`on_voice_state_update` は最初に `if member.bot: return` しているため、**Bot 自身が管理者に切断された・別の VC に移動させられた**ときのイベントも捨てています。

その結果、`channel_store`（永続化される）・`_speed`・ワーカーのタスクが残ったままになります。
`/leave` や自動退出のときの「全設定リセット」の挙動と食い違い、次に `/join` したとき、前回の読み上げチャンネルが残っています。

**推奨対応**: `member.id == self.bot.user.id and after.channel is None` の場合は、`/leave` と同じ後片付けをする。

---

### R-9 【中】discord.py の下限 `>=2.3.0` は、DAVE 必須化の後では不正確

- Discord は **2026年3月1日から**、DAVE（音声の E2EE）に対応していないクライアント・アプリの通話参加を受け付けなくなりました（Discord 公式ブログ・報道）。
- discord.py は **v2.7.0 で DAVE に対応**しました（`whats_new.rst`: "Add DAVE protocol support for voice connections"）。
  v2.7.1 では「`davey` が入っていないまま音声を使うとエラーにして警告」する変更が入っています。
- `uv.lock` は 2.7.1 で固定しているので、**CI と uv で入れた環境は問題ありません**。
  しかし `requirements.txt` と `pyproject.toml` は `discord.py[voice]>=2.3.0` です。2.6 以前が入った既存の venv で `pip install -r requirements.txt` を実行しても**更新されず**、VC に接続できません。
- README のバッジ「discord.py 2.3+」も、現在の事実と合っていません。

**推奨対応**: 下限を `discord.py[voice]>=2.7.1` に上げる（`pyproject.toml` / `requirements.txt` / README のバッジ）。`uv lock` も更新する。

---

### R-10 【低】README の systemd 節が Proxmox 節と矛盾し、root で実行する手順になっている

| | Proxmox 節（README:295, 313） | 「systemd 設定」節（README:577, 598） |
|---|---|---|
| ENGINE | `/opt/voicevox_engine/linux-cpu-x64/run` | `/opt/voicevox_engine/voicevox_engine`（Proxmox 節の手順では存在しないパス） |
| Bot | `.venv/bin/python bot.py` | `/usr/bin/python3 …`（**venv を使わないため依存がなく起動しない**） |
| 実行ユーザー | 指定なし（**root**） | `your_user` |

あわせて、README:279 の「`http://<コンテナIP>:50021/speakers` で確認」は、ENGINE を `--host 127.0.0.1` で起動する手順と矛盾します（外からは接続できない）。

**推奨対応**:

- systemd 節を Proxmox 節の内容に統一する。
- 専用ユーザー（`useradd -r yomiage`）と、最低限の hardening（`NoNewPrivileges=yes`、`ProtectSystem=strict`、`ReadWritePaths=/opt/Waras-Yomiage-Bot/data`）を入れる。
- 279 行目は `curl http://127.0.0.1:50021/speakers`（コンテナ内から）に直す。

---

## 構造的負債

### R-11 【中】`cogs/tts.py` が 1,295 行。prefix と slash を二重に定義している（19 + 19）

`ast` で集計した結果、`TTS` クラスは **1,168 行**で、次の役割が 1 つのクラスに入っています。

- 再生パイプライン（キュー・合成・キャッシュ・プレイヤー）
- VC への参加と退出
- 5 つのコマンドグループ（myvoice / listen / dict / autojoin / ignore）
- イベント処理

`commands.group` + `app_commands.Group` で、**同じコマンドを 2 回ずつ定義**しています（`@*_group.command` 19 個、`@*_app.command` 19 個）。

**推奨対応**（段階的に）:

1. コマンドグループを `commands.hybrid_group` に置き換え、定義を半分にする。discord.py 2.x の hybrid command は、`discord.Attachment` 引数も prefix / slash の両方で扱える。
2. パイプライン（`_synthesizer` / `_player` / `_pcm_cache` / `_in_flight`）を `tts_engine.py` のようなクラスに切り出し、Cog はコマンドだけを持つ。既存のパイプラインのテストは、そのまま新しいクラスに向けられる。
3. 辞書・自動参加・除外ユーザーのコマンドを、それぞれ別の Cog に分ける。

### R-12 【低】環境変数の読み込みが散らばっていて、検証もない

- `PREFIX`（4 箇所）・`DEFAULT_SPEAKER`（3 箇所）・`DEFAULT_SPEED` / `MAX_TEXT_LENGTH`（2 箇所）を、それぞれ別のファイルで `os.getenv` している。
- `int(...)` / `float(...)` が失敗したときに、どの変数が悪いのかわからない `ValueError` で起動に失敗する。
- `DEFAULT_SPEED` は 0.5〜2.0 の範囲を検証していない。`/speed` コマンドは範囲を検証しているので、それと食い違う。

**推奨対応**: `config.py` に `@dataclass(frozen=True) class Config` を作り、起動時に一度だけ読み込んで検証する。

### R-13 【低】未使用コード・lint 10 件

- `TTS._defer()`（`cogs/tts.py:520`）は、どこからも呼ばれていない。
- ユーザー ID を取り出す三項演算子が 4 箇所にコピーされている（`_myvoice_set` / `_reset` / `_info` / `_ignore_me`）。
- ruff の主な指摘（E501 以外）:
  - F401 未使用の import（`cogs/health.py:11`、`tests/test_tts_pipeline.py:8`）
  - F541（`cogs/uptime_kuma.py:11`）
  - E401（`cogs/utility.py:79` の関数内 `import platform, sys`）
  - E701（`cogs/tts.py:273-274`）
  - UP041（`voicevox.py:71` の `asyncio.TimeoutError`）
  - SIM105 ×2、ASYNC109 ×1
- `cogs/uptime_kuma.py` は Cog ではない（`setup` がない）のに `cogs/` に置かれている。

**推奨対応**: `ruff check --fix` で直せる 5 件を直し、CI に `ruff check` を追加する（`E501` は除外）。

### R-14 【低】`requirements.txt` と `pyproject.toml` / `uv.lock` の二重管理

README の手順は `pip install -r requirements.txt`（下限だけの指定で、ロックなし）、CI は `uv sync --locked` です。
**本番とCIで入るバージョンが一致する保証がありません**（R-9 はその実例）。

**推奨対応**: `uv export --no-dev --format requirements-txt > requirements.txt` で、ロックから生成するようにする。または README の手順を `uv sync` に統一する。

### R-15 【低】個人ドメインのハードコード、kuroneko 形式の `regex` フラグを無視

- `text_filter.py:12` で、`warasugi.com` を「わらすぎのURL」と読む設定がコードに埋め込まれている。運用者ごとに設定できるようにする（`.env` か辞書の機能で代わりになる）。
- `_parse_dict_json` は kuroneko 形式の `"regex": true` のエントリを、**正規表現ではなく文字列として**取り込む（`cogs/tts.py:982-984`）。
  黙って意味が変わるので、該当するエントリはスキップして件数を通知するべき。
  あわせて、`str(item["before"])` は `null` を `"None"` という文字列に変えてしまう。

### R-16 【低】Actions をタグで参照していて、SHA で固定していない

`.github/workflows/ci.yml` は `actions/checkout@v7`・`astral-sh/setup-uv@v10.2.0` を使っています（どちらもタグが存在することは `git ls-remote` で確認済み）。
タグは付け替えられるので、2025年の tj-actions 事件のようなサプライチェーン攻撃への耐性を高めるには、コミット SHA で固定するのが推奨されます。
`permissions: contents: read` が付いているので、影響は限定的です。

### R-17 【低】README / `/help` と実装のズレ

- `!leave` の別名: README は `quit, stop, bye`、実装と `/help` は `exit` も含む。
- `/help` の別名: `/help` の表示は `!h, !?`、実装は `info` も含む。
- README のスピーカー表は 40 キャラクター。VOICEVOX 公式サイトには 43 キャラクターが載っていて、**夜語トバリ・暁記ミタマ・里石ユカの 3 キャラクターが表にない**（ID は未確認なので、表に追加するなら実機の `/speakers` で確認すること）。
- README の Proxmox 推奨リソースは「4 vCPU」、CT 作成表は「Cores 2」。
- `/about` のフッターは「簡単・低遅延・直感的・エコ」、README のコンセプトは「シンプル・高速・直感的・エコ」。

---

## 良い点（維持すべきもの）

- `json_store` のアトミック書き込み（temp → fsync → rename → dir fsync）、3 世代バックアップ、スキーマを検証してのフォールバック。
- `data/*.json` が `0600` で作られる（`mkstemp` による）。
- 合成をギルド横断で共有する `_in_flight` と `shield` で、片方のギルドが `/leave` しても他方が止まらない設計。テストもある。
- VOICEVOX に 48kHz stereo で直接出力させて、FFmpeg を省く最適化。
- Uptime Kuma の push URL（トークン入り）を、ログに出さない配慮。
- `/health` を `HEALTH_ENABLED` と `OWNER_IDS` の二重で制限している。
- `self_deaf=True` で、音声を受信しない。

---

# 推奨アクションプラン

## フェーズ1: 1行〜数行で終わるもの（所要 1時間以内）

| 対象 | 作業 |
|---|---|
| R-3 | `allowed_mentions=discord.AllowedMentions.none()` を設定する |
| R-2 | `_parse_users_json` で bool を除外する。サイズ上限と回帰テストを追加する |
| R-9 | discord.py の下限を `>=2.7.1` に上げる（pyproject / requirements / README のバッジ） |
| L-8 | `.env.example` の実在形式の ID と個人ドメインを、プレースホルダに置き換える |
| R-13 | `ruff check --fix` と、未使用の `_defer` の削除 |

## フェーズ2: 数時間規模（権限・データ・クレジット）

| 対象 | 作業 |
|---|---|
| R-1 | `/listen add` で、実行者（と VC メンバー）の閲覧権限を確認する |
| R-4 | 辞書を適用する前の切り詰め。辞書の import / remove に権限を付ける |
| R-5, R-6 | 権限不足・引数ミス・サブコマンドなしのときに、ephemeral で返信する |
| L-1 | キャラクター別のクレジット表記の上書き表 |
| L-4 | `on_guild_remove` でのデータ削除。README のデータ表と Webhook の記述を更新する |
| R-10 | README の systemd 節を統一し、専用ユーザーで実行する手順にする |

## フェーズ3: 設計変更

| 対象 | 作業 |
|---|---|
| R-11 | `hybrid_group` への統合と、パイプラインのクラス分離 |
| R-12 | `config.py` に設定をまとめる |
| L-2, L-3 | `/about` に利用中のクレジット一覧を出す。`ALLOWED_SPEAKERS` を追加する |
| R-14 | 依存定義を uv に一本化する |

## フェーズ4: 長期

- R-7, R-8, R-15, R-16, R-17 の順に、ついでのタイミングで対応する。
- CI に `ruff check` を追加する。
- 公開運用する場合は `PRIVACY.md` を作り、Developer Portal に URL を登録する（L-4）。

---

## 所見

MuseHeart の問題の中心は「ライセンスの混入」と「長年の負債」でした。本 Bot の問題の中心は、**機能が増えるたびに権限設計が追いついていない**ことです（`/listen`・`/dict`・`/speed` は誰でも実行でき、エラー時は無言）。
法務面は、VOICEVOX 規約への配慮がすでに README に入っているので、**キャラクター別のクレジット表記を正確にする**ことと、**サーバーから退出したときのデータ削除**の 2 点を対応すれば、個人で運用する範囲では十分な水準になると考えます。

なお、このレビューは法的助言ではありません。キャラクター別の規約と Discord の規約の本文は、この環境から取得できなかったため、**「要原典確認」の項目は公開運用の前に一次資料で確認してください**。
