# Waras-Yomiage-Bot リーガル / リファクタリング レビュー報告書

| 項目 | 内容 |
|---|---|
| 対象リポジトリ | `warasugitewara/Waras-Yomiage-Bot` |
| 対象コミット | `e14ace6`（`feat: 発言者名の読み上げ（/readname）を追加`） |
| レビュー日 | 2026-10-01 |
| 対象範囲 | Python 22 ファイル（本体 16 + テスト 6）/ 約 3,500 行、README・`.env.example`・CI 定義 |
| きっかけ | 姉妹プロジェクト `JP-MuseHeart-MusicBot` のレビュー（同リポジトリ `docs/legal-and-refactoring-review.md`）で問題が見つかったため、同じ観点で本 Bot を点検した |
| 位置づけ | 技術的なレビューです。**法的助言ではありません**。「要原典確認」の項目は、公開運用の前に一次資料で確認してください |

---

## 目次

1. [結論（エグゼクティブサマリー）](#summary)
2. [指摘一覧（優先度順）](#findings)
3. [調査方法・検証状況・限界](#method)
4. [第1部 リーガル（ライセンス・法務）](#legal)
5. [第2部 リファクタリング / コード品質](#code)
6. [維持すべき良い点](#good)
7. [アクションプラン（チェックリスト）](#plan)
8. [参考資料](#refs)
9. [付録A 再現手順](#appendix-a)
10. [付録B MuseHeart 報告書の訂正](#appendix-b)

---

<a id="summary"></a>

## 1. 結論（エグゼクティブサマリー）

**ライセンス面は健全です。** MuseHeart で問題になった GPL / AGPL の混入に当たる問題はありません。本 Bot は MIT で、依存ライブラリ 26 件もすべて許容型（permissive）のライセンスです。VOICEVOX ENGINE も FFmpeg も同梱していません。全 103 コミットを走査しましたが、秘密情報の混入もありませんでした。

**リーガルで対応が必要なのは 2 点です。**

1. **VOICEVOX のクレジット表記**: 一部のキャラクターでは、指定された表記の形式と Bot が自動生成する表記が一致しません。また、VC で音声を聞いている人からクレジットが見えません（L-1・L-2）。
2. **データ削除の抜け**: Bot がサーバーから退出しても、そのサーバーのデータが残ります（L-4）。

**コード面の問題の中心は、機能の追加に権限設計が追いついていないことです。** 次の 3 件は、実際に動かす・ソースを読むなどして裏付けを取りました。

| | 内容 | 裏付け |
|---|---|---|
| 🔴 | `/owner import_users` に `speaker_id: true` が含まれていると、**全ユーザーのボイス設定が消える** | 再現済み |
| 🔴 | 権限のない一般メンバーが、`!listen add <ID>` で**自分には見えない非公開チャンネルを VC で読み上げさせられる** | discord.py のソースで確認 |
| 🟠 | 辞書を上限の 5,000 件まで登録すると、**メッセージ 1 件ごとにイベントループが最大 184ms 止まる**。辞書の編集には権限が要らない | 実測 |

一方、テスト 46 件・型エラー 0・CI・アトミックな JSON 保存がそろっていて、**基礎体力は MuseHeart より大幅に良い状態**です。指摘のほとんどは「数行の修正」で直ります（[アクションプラン](#plan) のフェーズ1・2）。

---

<a id="findings"></a>

## 2. 指摘一覧（優先度順）

重要度: 🔴 高 / 🟠 中 / 🟡 低 / ⚪ 情報 / ✅ 問題なし。「工数」の目安は S = 1 時間以内、M = 数時間、L = 設計変更。

| 優先 | ID | 重要度 | 分類 | 概要 | 裏付け | 工数 |
|---|---|---|---|---|---|---|
| 1 | [R-2](#r-2) | 🔴 | バグ | `/owner import_users` が bool を受け入れ、全ユーザー設定が消える | **再現済み** | S |
| 2 | [R-1](#r-1) | 🔴 | セキュリティ | `/listen add` で閲覧権限のない非公開チャンネルを読み上げ対象にできる | ソース確認 | S |
| 3 | [R-3](#r-3) | 🟠 | セキュリティ | `allowed_mentions` が未設定で、バッククォートもエスケープしていないため、`@everyone` を注入できる | 経路のみ確認 | S |
| 4 | [R-9](#r-9) | 🟠 | 依存 | discord.py の下限 `>=2.3.0` が、DAVE の必須化後は不正確 | 一次資料確認 | S |
| 5 | [R-4](#r-4) | 🟠 | 性能 / DoS | 辞書 5,000 件でメッセージ 1 件あたり最大 184ms 処理が止まる。辞書の編集に権限不要 | **実測** | S〜M |
| 6 | [R-5](#r-5) | 🟠 | UX バグ | 権限不足・引数ミスのときに無反応。スラッシュコマンドでは「応答しませんでした」になる | ソース確認 | M |
| 7 | [L-1](#l-1) | 🟠 | 規約 | 自動生成のクレジット表記が、4 キャラクターで指定の形式と一致しない | 公式サイトで確認 | S |
| 8 | [L-2](#l-2) | 🟠 | 規約 | VC で聞いている人に対して、クレジットが表示されていない | 公式規約・Q&A で確認 | M |
| 9 | [L-4](#l-4) | 🟡〜🟠 | プライバシー | サーバーから退出してもデータが残る。README の記述と実装に一部ズレがある | grep で確認 | M |
| 10 | [R-11](#r-11) | 🟠 | 構造 | `cogs/tts.py` が 1,295 行。prefix と slash を二重に定義している（19 + 19） | ast で集計 | L |
| 11 | [L-3](#l-3) | 🟡〜🟠 | 規約 | 非商用限定や、法人利用に事前確認が必要なキャラクターも選べてしまう | 公式サイトで確認 | M |
| 12 | [R-6](#r-6) | 🟡 | UX バグ | `!myvoice` などをサブコマンドなしで打つと何も返らない | ソース確認 | S |
| 13 | [R-10](#r-10) | 🟡 | ドキュメント | README の systemd 節が Proxmox 節と矛盾し、root で実行する手順になっている | 確認 | S |
| 14 | [L-8](#l-8) | 🟡 | 設定例 | `.env.example` に実在形式のユーザー ID と個人ドメインが入っている | 確認 | S |
| 15 | [R-13](#r-13) | 🟡 | 品質 | 未使用コード・lint 10 件 | ruff | S |
| 16 | [R-7](#r-7) | 🟡 | 運用 | `/dict list` が全件を公開チャンネルに数十通で投稿する | コード確認 | S |
| 17 | [R-8](#r-8) | 🟡 | バグ | Bot が外部から VC を切断されたとき、状態が片付かない | コード確認 | S |
| 18 | [R-12](#r-12) | 🟡 | 構造 | 環境変数の読み込みが散らばっていて、検証もない | grep | M |
| 19 | [R-14](#r-14) | 🟡 | 依存 | `requirements.txt` と `uv.lock` の二重管理 | 確認 | S |
| 20 | [R-15](#r-15) | 🟡 | 汎用性 | 個人ドメインのハードコード。kuroneko 形式の `regex` フラグを無視している | 確認 | S |
| 21 | [R-16](#r-16) | 🟡 | CI | Actions をタグで参照していて、SHA で固定していない | 確認 | S |
| 22 | [R-17](#r-17) | 🟡 | ドキュメント | README・`/help` と実装のズレ | 確認 | S |
| — | [L-5](#l-5) | ⚪ | 情報 | 特権インテントの申請基準が「ユニークユーザー 1 万人」に変わった | 一次資料で確認 | — |
| — | [L-6](#l-6) | ✅ | ライセンス | 依存ライブラリ 26 件にコピーレフトなし | 確認 | — |
| — | [L-7](#l-7) | ✅ | ライセンス | LICENCE・著作権表示、VOICEVOX ENGINE / FFmpeg の扱いは適切 | 確認 | — |

---

<a id="method"></a>

## 3. 調査方法・検証状況・限界

### 3.1 実施した検証

| 項目 | 方法 | 結果 |
|---|---|---|
| テスト | `uv sync --locked` → `uv run pytest -q` | **46 passed** |
| 型検査 | `uvx pyright@1.1.414 .`（CI と同じ版） | **0 errors** |
| Lint | `uvx ruff check --select E,F,W,B,UP,SIM,ASYNC` | E501（行長）148 件を除くと **10 件** |
| 依存ライブラリのライセンス | `.venv` 内の全パッケージの METADATA を読み、環境外の 2 件は PyPI の JSON API で確認 | コピーレフト **0 件** |
| 秘密情報の混入 | `git fetch --unshallow` で**全 103 コミット**を取得し、次を正規表現で走査: Bot トークンの形式、Webhook URL、Uptime Kuma の push トークン、`.env` / `data/*.json` がコミットされていないか | **検出 0 件**（プレースホルダの `xxxxxxxxxxxx` のみ） |
| バグ候補 | 再現スクリプトを実行（[付録A](#appendix-a)）、使用中の discord.py 2.7.1 のソースを読む | 各項目に裏付けの種類を明記 |
| コード規模 | `ast` で関数・クラスの行数を集計 | `TTS` クラスが 1,168 行で最大 |

### 3.2 外部情報の取得元

| 情報 | 取得元 | 状況 |
|---|---|---|
| VOICEVOX のソフトウェア利用規約・Q&A・キャラクター別の規約概要 | VOICEVOX 公式サイトのソース（GitHub `VOICEVOX/voicevox_blog`、`934acc9` / 2026-09-07） | ✅ 原文を確認 |
| discord.py の DAVE 対応 | `Rapptz/discord.py` の `docs/whats_new.rst`（master） | ✅ 確認 |
| Discord による DAVE の必須化の時期 | Discord 公式ブログ・報道 | ✅ 確認 |
| 特権インテントの申請基準 | GitHub `discord/discord-api-docs`（`86f0a46` / 2026-09-30） | ✅ 確認 |
| **各キャラクターの利用規約の本文**（zunko.jp ほか） | — | ⚠️ ネットワーク制限で**取得できず**。VOICEVOX 公式サイトの概要で代用 |
| **Discord Developer Policy / Developer Terms の本文** | — | ⚠️ **取得できず**（`discord-api-docs` 側は外部リンクだけのスタブ） |

### 3.3 このレビューで確認していないこと

- 実際の Discord サーバーでの動作（特に R-1 のスラッシュ版、R-3 の通知が実際に飛ぶか）
- 実機の VOICEVOX ENGINE が `/speakers` で返すキャラクター名（L-1 に影響）
- 「要原典確認」と付けた各規約の本文

---

<a id="legal"></a>

## 4. 第1部 リーガル（ライセンス・法務）

<a id="l-1"></a>

### L-1 🟠 自動生成されるクレジット表記が、一部キャラクターで指定の形式と一致しない

`cogs/tts.py:513-518` の `_resolve_credit()` は、どのキャラクターでも一律に `f"VOICEVOX:{entry[0]}"`（`entry[0]` は ENGINE の `/speakers` が返すキャラクター名）を表示します（`/myvoice set`・`/myvoice info`）。

VOICEVOX 公式サイトのキャラクター別規約の概要（`src/assets/library-term-intro-markdowns/*.md`）では、次の 4 キャラクターに**キャラクター名だけではない表記**が指定されています。

| キャラクター | 公式サイトに書かれた指定の表記 | Bot が生成する表記（※） |
|---|---|---|
| もち子さん | `VOICEVOX:もち子(cv 明日葉よもぎ)` | `VOICEVOX:もち子さん` |
| Voidoll | `VOICEVOX:Voidoll(CV:丹下桜)` | `VOICEVOX:Voidoll` |
| ユーレイちゃん | `VOICEVOX:ユーレイちゃん(CV:神崎零)` | `VOICEVOX:ユーレイちゃん` |
| 里石ユカ | `VOICEVOX:里石ユカ（つぼみ）` | `VOICEVOX:里石ユカ` |

※ 公式サイトの `characterInfos/*.ts` の `name` と README のスピーカー表は、どちらも「もち子さん」「Voidoll」「ユーレイちゃん」となっています。ENGINE も同じ名前を返すと仮定した場合の表記です。**実機の ENGINE では確認していません。**

**推奨対応**: `{キャラクター名: クレジット表記}` の上書き表を持ち、該当するキャラクターだけ差し替える（数行）。上書き表には、出典として各キャラクターの規約 URL（公式サイトの `characterInfos/*.ts` にある `policyUrl`）をコメントで残す。**要原典確認。**

<a id="l-2"></a>

### L-2 🟠 VC で聞いている人に対して、クレジットが表示されていない

VOICEVOX のソフトウェア利用規約（`src/pages/term.md`）:

> 2. 作成された音声を利用する際は、各音声ライブラリの規約に従ってください
> 3. 作成された音声の利用を他者に許諾する際は、当該他者に対し本許諾内容の 2 及び 3 の遵守を義務付けてください
>
> ご利用の際は VOICEVOX を利用したことがわかるクレジット表記が必要です。

VOICEVOX の Q&A（`src/pages/qa/index.md`）:

> Q. スピーカーでの音声案内など、機械で音声を流したい場合のクレジット記載はどうすれば良いですか？
> 音声の最初や最後に音声クレジットを挿入するか、その機械や周辺にてクレジットを表記してください。
> キャラクターの利用規約に案内がある場合はそちらを優先してください。

**現状**

- 音声を選んだ本人には、`/myvoice set` と `/myvoice info` でクレジットが表示される。
- `/about` に出るのは「VOICEVOX:ずんだもん ほか各キャラクター」だけ。
- ところが、**VC で実際に音声を聞いている他のメンバー**は、どのキャラクターの声かを Bot の周辺で確認できない。
- 規約 3 項（利用者に規約の遵守を義務付ける）については、README がサーバー管理者に「利用者にも求めてください」と書いている。しかし、**Bot の中には利用者向けの案内がない**。

**推奨対応**（規約の解釈を含みます。安全側に倒した提案です）

1. Bot の Discord プロフィール（About Me）に「音声: VOICEVOX（各キャラクター）/ クレジットは `/about` 参照」と書くよう、README で運用者に案内する（コード変更なし）。
2. `/about` に**利用中のスピーカーのクレジット一覧**を出す（`users.json` に入っている speaker_id とデフォルトの話者から生成する）。
3. `/join` で接続したときや `/help` に、「音声は VOICEVOX と各キャラクターの利用規約に従ってご利用ください」という一文を入れる。

<a id="l-3"></a>

### L-3 🟡〜🟠 非商用限定や、法人利用に事前確認が必要なキャラクターも選べてしまう（運用形態による）

`/myvoice set` は、ENGINE が返す**すべての**スタイル ID を受け付けます（`cogs/tts.py:644-663`）。公式サイトの概要によると、キャラクターごとに次の条件があります（**要原典確認**）。

| 条件 | キャラクター |
|---|---|
| 非商用のみ（同人利用や配信による収入は可） | No.7、ユーレイちゃん |
| 企業が関わる利用は事前確認が必要 | 青山龍星、後鬼、もち子さん |
| 法人による利用は個別に問い合わせ | Voidoll |
| 商用利用は個別に問い合わせ | ぞん子 |

個人が非営利で運用している現状では、どれにも当たらないと考えられます。ただし、**企業のサーバーへの導入**や**有償での運用**をする場合は、運用者がこれらの条件を満たす必要があります。

**推奨対応**: `.env` に `ALLOWED_SPEAKERS` / `DENIED_SPEAKERS` を追加し、運用者が使える話者を絞れるようにする。README の「クレジット・利用規約」に「法人・商用で運用する場合は、キャラクターごとの条件を確認すること」と追記する。

<a id="l-4"></a>

### L-4 🟡〜🟠 プライバシー: サーバーから退出してもデータが残る。README と実装に一部ズレがある

README の「データの取り扱い」は、保存先・内容・削除方法を表にしていて、MuseHeart（プライバシーに関する文書なし）よりずっと良い状態です。ほかにも良い点があります。

- `json_store.save_json()` は `tempfile.mkstemp` を使うので、**`data/*.json` とバックアップは `0600` で作られる**（実測）。
- Bot は `self_deaf=True` で VC に参加し、音声を受信しない。

**見つかった不足**

| # | 内容 | 根拠 |
|---|---|---|
| (a) | **Bot がサーバーから退出・キックされても、そのサーバーのデータが残る**（読み上げチャンネル・辞書・自動参加・除外ユーザー ID） | `on_guild_remove` のハンドラがない（grep で確認） |
| (b) | `users.json` のユーザー ID は、本人が `/myvoice reset` しない限り消えない（Discord アカウントを削除しても残る） | `user_store.py` |
| (c) | README には、Webhook で送るのは「サーバー名・ユーザー名・コマンド名」とある。実際には **guild_id / channel_id とトレースバック**も送っている | `cogs/tts.py:318-321, 1222-1225`、`webhook_logger.py:85-91` |
| (d) | README には「第三者へ提供しません」とある。しかし `VOICEVOX_URL` を別ホストに向けた場合、**そのホストにメッセージ本文が送られる**ことに触れていない。さらに、URL が `http://` の場合は**本文が平文のままネットワークを流れる**（`https://` なら TLS で保護される。`VoicevoxClient` は `VOICEVOX_URL` をそのまま使う） | `voicevox.py:20, 57, 94-98` |

**Discord 側の要件**（Developer Policy / Developer Terms の本文は取得できなかったため、**要原典確認**）

- アプリの設定には `privacy_policy_url` の欄があり、収益化を申請する場合はプライバシーポリシーへのリンクが要件として明記されています（`discord-api-docs` の `developers/monetization/enabling-monetization.mdx`）。
- 特権インテントの申請ガイドでは、データを保存する場合に「なぜ必要か、保持ポリシー、セキュリティ対策」を説明するよう求めています。

**推奨対応**

1. `on_guild_remove` で、そのサーバーの `channel_store` / `word_dict` / `guild_settings` を削除する（10 行程度）。
2. README のデータ表に「サーバーから退出したときの扱い」と「保持期間」を追記し、Webhook の送信項目を実装に合わせる。
3. README に次の 2 点を追記する。(1) 外部の ENGINE を使う場合は、そのホストにメッセージ本文が送られる。(2) `http://` を使うのは同じホストか信頼できるプライベートネットワークに限り、それ以外では `https://`（リバースプロキシ等）を使う。
4. 公開運用に備えて、`PRIVACY.md` のひな形を用意する（README の表をほぼそのまま使える）。

<a id="l-5"></a>

### L-5 ⚪ 特権インテントの申請基準が変わった

`discord-api-docs` の `getting-started-with-privileged-intent-review.mdx`（2026-09-30 時点）:

> Previously, apps in fewer than 100 servers could access Privileged Intents by toggling them on in the Developer Portal, and apps in 100+ servers needed to apply for access. That threshold is now based on the number of unique users who can see your app across all the servers it's in. If that number exceeds 10,000, your app needs to apply for Privileged Intent access.

本 Bot は、読み上げのために Message Content Intent を**必ず**必要とします（`bot.py:25`）。導入しているサーバーが少なくても、**各サーバーで Bot が見えるユーザーの合計が 1 万人を超えると申請が必要**です。申請では、具体的な用途と、データをどう扱うか（保存するのか、メモリ上で処理して捨てるのか）を説明します。README の「メッセージ本文はディスクに保存しません」は、そのまま申請理由に使えます。

<a id="l-6"></a>

### L-6 ✅ 依存ライブラリのライセンス

`uv.lock` の全 26 パッケージを確認しました。`audioop-lts`（Python 3.13 以上でのみ使用）と `colorama`（Windows でのみ使用）は、PyPI の JSON API で確認しています。

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

GPL / LGPL / AGPL は **0 件**です。依存はそれぞれの環境で `pip` / `uv` を使ってインストールする形で、本リポジトリは同梱・再配布していません。そのため、Apache-2.0 の NOTICE を同梱する義務も生じません。

<a id="l-7"></a>

### L-7 ✅ LICENCE・著作権表示、VOICEVOX ENGINE / FFmpeg の扱い

- `LICENCE` は MIT の全文で、著作権表示 `Copyright (c) 2026 .warasugi` があります（MuseHeart の L-3 に当たる問題はありません）。最初のコミットが 2026-04-30 なので、年も合っています。`pyproject.toml` の `license = "MIT"` とも一致しています。
- VOICEVOX ENGINE は同梱していません。README の手順も公式の Releases から取得する形なので、VOICEVOX 規約の禁止事項「本ソフトウェアの全てまたは一部を無断で再配布すること」には当たりません。
- FFmpeg は外部プロセスとして呼び出しているだけで（`cogs/tts.py:99-107`）、同梱もリンクもしていません。
- AI 支援の表記について、MuseHeart の L-11(c) のような「@claude (Anthropic)」の誤った帰属はありません。

<a id="l-8"></a>

### L-8 🟡 `.env.example` に実在形式のユーザー ID と個人ドメインが入っている

- `.env.example:30` の `# OWNER_IDS=811515262238064640` は、他の例（`123456789012345678` など）と違い、実在する形式の ID です。秘密情報ではありませんが、運用者がそのままコピーすると、**第三者にオーナー権限を与える**事故の元になります。
- `.env.example:41` の `status.warasugi.com` と、`text_filter.py:12` の `warasugi.com` → 「わらすぎのURL」は、個人のドメインが汎用の設定例やコードに入っているものです（法的な問題ではありません。R-15 を参照）。

**推奨対応**: ID は `123456789012345678` に、URL は `https://your-uptime-kuma/...` に置き換える。

---

<a id="code"></a>

## 5. 第2部 リファクタリング / コード品質

<a id="r-1"></a>

### R-1 🔴 `/listen add` で、閲覧権限のない非公開チャンネルを読み上げ対象にできる

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

- コマンドに権限チェックがない（`@has_permissions` を付けていない）。
- discord.py 2.7.1 の `TextChannelConverter`（`ext/commands/converter.py:470-498`）は、`guild.get_channel(channel_id)` で ID からチャンネルを引くだけで、**実行者がそのチャンネルを閲覧できるかを確認しない**。

**攻撃シナリオ**

1. 一般メンバーが、自分には見えない運営チャンネルの ID を入手する（開発者モードや、過去に貼られたリンクから取れる）。
2. その ID を `!listen add 123…` に渡す。
3. Bot がそのチャンネルを読める権限を持っていれば、**運営チャンネルの投稿が、そのメンバーのいる VC で読み上げられる**。

スラッシュ版で Discord がチャンネルの選択肢を権限で絞るかどうかは、未検証です。prefix 版だけで、この攻撃は成立します。

**推奨対応**: `_listen_add` で `channel.permissions_for(実行者).read_messages` を確認する。望ましくは、VC にいるメンバー全員がそのチャンネルを閲覧できることも確認する。`/listen remove` には、`manage_channels` 程度の権限を付けることを検討する。

<a id="r-2"></a>

### R-2 🔴 `/owner import_users` が bool を受け入れ、全ユーザー設定が消える

`cogs/owner.py:154` の検証は `isinstance(spk, int)` だけです。Python では `bool` が `int` のサブクラスなので、`true` が通ってしまいます。一方、読み込み側の `user_store._validate_users()` は bool を拒否します。**書き込みと読み込みで検証が食い違っている**のが原因です（再現手順は [付録A-1](#appendix-a)）。

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

メモリ上には `True` が残るので、`/myvoice set` のたびに、その値を含んだ `users.json` 全体が書き直されます。**3 回保存されると世代バックアップが 3 つとも不正になり、次の起動で全ユーザーのボイス設定が空になります。**

ほかにも、`_import_users` にはサイズの上限がない（辞書のインポートは 1MB まで）ことと、speaker_id が実在するかを検証していないことが見つかりました。

**推奨対応**: 検証を `user_store._validate_users` と同じ判定（`isinstance(v, int) and not isinstance(v, bool)`）にそろえ、できれば 1 つの関数にまとめる。サイズの上限と回帰テストも追加する。

<a id="r-3"></a>

### R-3 🟠 `allowed_mentions` が未設定で、バッククォートもエスケープしていないため、`@everyone` を注入できる

`bot.py` は `allowed_mentions` を設定していません（grep で 0 件）。この状態では、Bot が送る本文に `@everyone` が含まれ、かつ **Bot がそのサーバーで「@everyone へのメンション」権限を持っていると、全員に通知が飛びます**。

ユーザーが入力した文字列を、エスケープせずにバッククォート（`` ` ``）で囲んで返している箇所があります。

| 箇所 | 入力元 |
|---|---|
| `cogs/tts.py:836`（`` f"📖 `{word}` → `{reading}` を辞書に追加しました。" ``） | `/dict add`（**権限不要**） |
| `cogs/tts.py:841, 848` | `/dict remove` |
| `cogs/tts.py:959` | `/dict import` のエラー |
| `cogs/utility.py:172`（`` f"⚠️ `{command}` というコマンドは見つかりません。" ``） | `!help`（prefix 版は ephemeral にならない） |

例えば `` !help x`@everyone `` と送ると、返信は `` ⚠️ `x`@everyone` というコマンドは… `` になります。入力に含めたバッククォートでコード表示が閉じるので、`@everyone` が**コード表示の外**に出ます。コード上の経路は確認しましたが、実際のサーバーで通知が飛ぶかは確認していません。

**推奨対応**（1 行）: `super().__init__()` に `allowed_mentions=discord.AllowedMentions.none()` を渡す。

<a id="r-4"></a>

### R-4 🟠 辞書 5,000 件でメッセージ 1 件あたり最大 184ms 処理が止まる。辞書の編集に権限は不要

`text_filter.filter_message()` は、辞書の全単語を `|` でつないだ 1 本の正規表現を作り、**長文カット（`max_length`）の前に、メッセージ全体へ**適用します。Python の `re` はこの形の正規表現を最適化しないため、処理時間は「メッセージ長 × 単語数」に比例します（計測手順は [付録A-2](#appendix-a)）。

| 辞書の件数 | 2,000 文字（ASCII） | 2,000 文字（日本語） | 4,000 文字（日本語） |
|---|---|---|---|
| 100 | 1.2 ms | 1.3 ms | 2.7 ms |
| 1,000 | 13.4 ms | 13.1 ms | 26.3 ms |
| 5,000（上限） | **85.6 ms** | **90.7 ms** | **184.4 ms** |

- `/dict add` と `/dict import` には権限チェックがないので、**一般メンバーでも 5,000 件まで登録できる**。
- 正規表現の処理中は GIL を握ったままなので、discord.py の音声送信スレッドも止まる。**読み上げの音が途切れる**原因になり得る。
- ほかにも、メッセージごとに辞書をコピーし（`word_dict.all()`）、`frozenset()` を作り直している（`cogs/tts.py:1253`、`text_filter.py:143`）。

**推奨対応**

1. 辞書を適用する前に、入力を `max_length` の数倍（例: 4 倍）で切り詰める。出力はどのみち `max_length` で切られるので、挙動は変わらない。
2. `/dict import`（特に `replace=True`）と `/dict remove` に権限を付ける。または、権限の要否を運用者が設定できるようにする。
3. コンパイル済みの正規表現を `WordDict` がギルドごとに保持し、辞書が変更されたときだけ作り直す。

<a id="r-5"></a>

### R-5 🟠 権限不足・引数ミスのときに無反応。スラッシュコマンドでは「応答しませんでした」になる

`bot.py:125-150` の `on_command_error` と `bot.py:152-178` の `_on_tree_error` は、`MissingPermissions` / `CheckFailure` / `BadArgument` / `MissingRequiredArgument` などのエラーを**何も返さずに `return`** しています。

- **prefix コマンド**: 権限のない人が `!autojoin add …` を実行したときや、`!speed abc` のように引数を間違えたときに、何も返らない。
- **スラッシュコマンド**: 応答しないまま終わるので、Discord に **「アプリケーションが応答しませんでした」** と表示される。経路は次の 2 つで、どちらも同じく無反応です。
  - `/autojoin`・`/ignore`（純粋なスラッシュコマンド）は `tree.on_error` に届く。
  - `/readname`・`/reload_speakers`（hybrid コマンド）は、discord.py 2.7.1 の `ext/commands/hybrid.py:455-480` で `on_command_error` に回される。

**推奨対応**: 握りつぶしているエラーごとに、短い ephemeral メッセージを返す。送信には既存の `discord_helpers.send_response` を使う（応答済みなら followup に切り替える処理がすでにある）。

<a id="r-6"></a>

### R-6 🟡 `!myvoice` などをサブコマンドなしで打つと何も返らない

`bot.py:29` で `help_command=None` にしています。discord.py 2.7.1 の `Context.send_help()`（`ext/commands/context.py:551-`）は、`bot.help_command` が `None` のときは何もせずに `None` を返します。そのため、次の 6 グループはサブコマンドなしで打つと無反応です: `myvoice` / `listen` / `dict` / `autojoin` / `ignore` / `owner`。

**推奨対応**: `_HELP_DATA` から該当するカテゴリを返す。

<a id="r-7"></a>

### R-7 🟡 `/dict list` が全件を公開チャンネルに数十通で投稿する

`_dict_list` は、辞書の全件を 1,900 文字ずつに分けて送ります。ephemeral（本人にだけ見える表示）ではありません。上限の 5,000 件が登録されていると**数十通の連投**になり、しかも権限なしで誰でも実行できます。

**推奨対応**: 件数が多い場合は JSON ファイルを添付する。または ephemeral にする。

<a id="r-8"></a>

### R-8 🟡 Bot が外部から VC を切断されたとき、状態が片付かない

`on_voice_state_update` は先頭で `if member.bot: return` しているため、管理者が Bot を切断・移動したときのイベントも捨ててしまいます。その結果、`channel_store`（永続化される）・`_speed`・ワーカーが残ります。`/leave` のときの「全設定リセット」と挙動が食い違います。

**推奨対応**: `member.id == self.bot.user.id and after.channel is None` の場合は、`/leave` と同じ後片付けをする。

<a id="r-9"></a>

### R-9 🟠 discord.py の下限 `>=2.3.0` が、DAVE の必須化後は不正確

- Discord は **2026 年 3 月 1 日から**、DAVE（音声の E2E 暗号化）に対応していないクライアント・アプリを通話に参加させていません。
- discord.py は **v2.7.0 で DAVE に対応**しました（"Add DAVE protocol support for voice connections"）。v2.7.1 では、`davey` が入っていない状態で音声を使うとエラーにして警告するようになっています。
- `uv.lock` は 2.7.1 に固定されているので、**uv で入れた環境と CI は問題ありません**。
- 問題は `requirements.txt` と `pyproject.toml` の指定が `>=2.3.0` のままであることです。2.6 以前が入っている venv では、`pip install -r requirements.txt` を実行しても**更新されず、VC に接続できません**。README のバッジ「discord.py 2.3+」も事実と合いません。

**推奨対応**: 下限を `discord.py[voice]>=2.7.1` に上げ、README のバッジも更新し、`uv lock` を実行する。

<a id="r-10"></a>

### R-10 🟡 README の systemd 節が Proxmox 節と矛盾し、root で実行する手順になっている

| | Proxmox 節（README:295, 313） | 「systemd 設定」節（README:577, 598） |
|---|---|---|
| ENGINE | `/opt/voicevox_engine/linux-cpu-x64/run` | `/opt/voicevox_engine/voicevox_engine`（Proxmox 節の手順では存在しないパス） |
| Bot | `.venv/bin/python bot.py` | `/usr/bin/python3 …`（**venv を使わないので依存ライブラリがなく、起動しない**） |
| 実行ユーザー | 指定なし（**root**） | `your_user` |

README:279 の「`http://<コンテナIP>:50021/speakers` で確認」も、ENGINE を `--host 127.0.0.1` で起動する手順と矛盾します。

**推奨対応**: 2 つの節を統一する。専用ユーザーで実行し、最低限の hardening を入れる（`NoNewPrivileges=yes`、`ProtectSystem=strict`、`ReadWritePaths=.../data`）。

<a id="r-11"></a>

### R-11 🟠 `cogs/tts.py` が 1,295 行。prefix と slash を二重に定義している（19 + 19）

`TTS` クラスは **1,168 行**あり、次の役割を 1 つのクラスで担っています。

- 再生パイプライン
- VC への参加と退出
- 5 つのコマンドグループ
- イベント処理

コマンドは `commands.group` と `app_commands.Group` で**同じものを 2 回ずつ定義**しています（19 + 19）。

**推奨対応**（段階的に）

1. `commands.hybrid_group` に統合し、定義を半分にする（`discord.Attachment` を受け取る引数も、hybrid で両対応できる）。
2. パイプライン（`_synthesizer` / `_player` / `_pcm_cache` / `_in_flight`）をクラスとして切り出す。既存のパイプラインのテストは、そのまま移せる。
3. 辞書・自動参加・除外ユーザーを、それぞれ別の Cog に分ける。

<a id="r-12"></a>

### R-12 🟡 環境変数の読み込みが散らばっていて、検証もない

- 同じ環境変数を複数のファイルで `os.getenv` している: `PREFIX`（4 箇所）、`DEFAULT_SPEAKER`（3 箇所）、`DEFAULT_SPEED` / `MAX_TEXT_LENGTH`（各 2 箇所）。
- 値が不正なときは、どの変数が原因か分からない `ValueError` で起動に失敗する。
- `DEFAULT_SPEED` の範囲（0.5〜2.0）を検証していない。

**推奨対応**: `config.py` に `@dataclass(frozen=True)` の設定クラスを作り、起動時に 1 回だけ読み込んで検証する。

<a id="r-13"></a>

### R-13 🟡 未使用コード・lint 10 件

- `TTS._defer()`（`cogs/tts.py:520`）はどこからも呼ばれていない。
- ユーザー ID を取り出す三項演算子が、4 箇所にコピーされている。
- ruff の指摘（E501 を除く）:
  - F401 ×2（`cogs/health.py:11`、`tests/test_tts_pipeline.py:8`）
  - F541（`cogs/uptime_kuma.py:11`）
  - E401（`cogs/utility.py:79`）
  - E701 ×2（`cogs/tts.py:273-274`）
  - UP041（`voicevox.py:71`）
  - SIM105 ×2
  - ASYNC109 ×1
- `cogs/uptime_kuma.py` は Cog ではない（`setup` がない）のに、`cogs/` に置かれている。

**推奨対応**: `ruff check --fix` を実行し、CI に `ruff check`（E501 を除外）を追加する。

<a id="r-14"></a>

### R-14 🟡 `requirements.txt` と `uv.lock` の二重管理

README の手順は `pip install -r requirements.txt`（下限の指定だけ）で、CI は `uv sync --locked` です。本番環境と CI で、入るバージョンが一致する保証がありません（R-9 がその実例です）。

**推奨対応**: `requirements.txt` を `uv export --no-dev --format requirements-txt` で生成する。または、README の手順を uv に統一する。

<a id="r-15"></a>

### R-15 🟡 個人ドメインのハードコード、kuroneko 形式の `regex` フラグを無視

- `text_filter.py:12` の `warasugi.com` → 「わらすぎのURL」は、運用者ごとに設定できるようにする。
- `_parse_dict_json`（`cogs/tts.py:982-984`）は、kuroneko 形式の `"regex": true` のエントリを、正規表現ではなく**ただの文字列として**取り込む。意味が黙って変わるので、そのエントリはスキップして件数を通知するべき。
- `str(item["before"])` は、`null` を `"None"` という文字列に変えてしまう。

<a id="r-16"></a>

### R-16 🟡 Actions をタグで参照していて、SHA で固定していない

`actions/checkout@v7`・`astral-sh/setup-uv@v10.2.0`（いずれもタグが存在することは `git ls-remote` で確認）。タグは後から付け替えられるため、2025 年の tj-actions 事件のようなサプライチェーン攻撃への耐性を上げるには、コミット SHA で固定するのが推奨です。`permissions: contents: read` が付いているので、影響は限定的です。

<a id="r-17"></a>

### R-17 🟡 README・`/help` と実装のズレ

- `!leave` の別名: README は `quit, stop, bye`、実装は `exit` も含む。
- `/help` の別名: 表示は `!h, !?`、実装は `info` も含む。
- スピーカー表: README は 40 キャラクター。VOICEVOX 公式サイトは 43 キャラクターで、**夜語トバリ・暁記ミタマ・里石ユカが README にない**（ID は実機の `/speakers` で確認すること）。
- Proxmox の推奨リソースは「4 vCPU」だが、CT 作成の表は「Cores 2」。
- コンセプト: `/about` は「簡単・低遅延・直感的・エコ」、README は「シンプル・高速・直感的・エコ」。

---

<a id="good"></a>

## 6. 維持すべき良い点

- `json_store`: アトミック書き込み（temp → fsync → rename → dir fsync）、3 世代のバックアップ、スキーマを検証して壊れていればバックアップに戻る仕組み。
- `data/*.json` が `0600` で作られる。
- ギルドをまたいで合成を共有する仕組み（`_in_flight` + `shield`）。片方のギルドが `/leave` しても、もう片方は止まらない。これにはテストもある。
- VOICEVOX に 48kHz stereo で直接出力させ、FFmpeg による変換を省いている。
- Uptime Kuma の push URL（トークンを含む）をログに出さない。
- `/health` は `HEALTH_ENABLED` と `OWNER_IDS` の二重で制限している。
- `self_deaf=True` で VC に参加し、音声を受信しない。
- テスト 46 件、Pyright のエラー 0、CI あり。

---

<a id="plan"></a>

## 7. アクションプラン（チェックリスト）

### フェーズ1: 数行で終わるもの（1 時間以内）

- [ ] **R-3** `allowed_mentions=discord.AllowedMentions.none()` を設定する
- [ ] **R-2** `_parse_users_json` で bool を除外し、サイズの上限と回帰テストを追加する
- [ ] **R-9** discord.py の下限を `>=2.7.1` に上げる（pyproject / requirements / README のバッジ / `uv lock`）
- [ ] **L-8** `.env.example` の実在形式の ID と個人ドメインをプレースホルダに置き換える
- [ ] **R-13** `ruff check --fix` を実行し、未使用の `_defer` を削除する

### フェーズ2: 数時間規模（権限・データ・クレジット）

- [ ] **R-1** `/listen add` で閲覧権限を確認する
- [ ] **R-4** 辞書を適用する前に入力を切り詰める。辞書の import / remove に権限を付ける
- [ ] **R-5 / R-6** 権限不足・引数ミス・サブコマンドなしのときに ephemeral で返信する
- [ ] **L-1** キャラクター別のクレジット表記の上書き表を作る
- [ ] **L-4** `on_guild_remove` でデータを削除する。README のデータ表と Webhook の記述を更新する
- [ ] **R-10** README の systemd 節を統一し、専用ユーザーで実行する手順にする

### フェーズ3: 設計変更

- [ ] **R-11** `hybrid_group` に統合し、パイプラインをクラスとして切り出す
- [ ] **R-12** `config.py` で設定を一元化する
- [ ] **L-2 / L-3** `/about` にクレジット一覧を表示する。`ALLOWED_SPEAKERS` を追加する
- [ ] **R-14** 依存定義を uv に一本化する

### フェーズ4: 長期・ついでに

- [ ] **R-7 / R-8 / R-15 / R-16 / R-17**
- [ ] CI に `ruff check` を追加する
- [ ] 公開運用する場合は `PRIVACY.md` を作り、Developer Portal に URL を登録する（L-4）
- [ ] 「要原典確認」の項目（L-1・L-3・L-4）を一次資料で確認する

---

<a id="refs"></a>

## 8. 参考資料

| 資料 | URL | 本報告での用途 |
|---|---|---|
| VOICEVOX 公式サイトのソース（`934acc9` / 2026-09-07） | https://github.com/VOICEVOX/voicevox_blog | ソフトウェア利用規約（`src/pages/term.md`）、Q&A（`src/pages/qa/index.md`）、キャラクター別の規約概要（`src/assets/library-term-intro-markdowns/`）、規約 URL（`src/constants/characterInfos/`） |
| VOICEVOX ソフトウェア利用規約 | https://voicevox.hiroshiba.jp/term/ | 上記の公開ページ（この環境からはアクセス不可） |
| 東北ずん子・ずんだもんプロジェクト 音源利用規約 | https://zunko.jp/con_ongen_kiyaku.html | ずんだもん・四国めたんなどの規約（**未取得・要原典確認**） |
| discord.py 変更履歴 | https://github.com/Rapptz/discord.py/blob/master/docs/whats_new.rst | DAVE 対応が v2.7.0 であること |
| Discord 公式ブログ（E2EE） | https://discord.com/blog/every-voice-and-video-call-on-discord-is-now-end-to-end-encrypted | DAVE の全面適用 |
| DAVE 必須化の告知（報道） | https://www.elevenforum.com/t/starting-march-1st-2026-clients-and-apps-without-dave-support-will-no-longer-be-able-to-participate-in-discord-calls.39488/latest | 2026-03-01 から必須 |
| Discord API ドキュメント（`86f0a46` / 2026-09-30） | https://github.com/discord/discord-api-docs | 特権インテントの申請基準、`privacy_policy_url` |
| Discord Developer Policy | https://support-dev.discord.com/hc/en-us/articles/8563934450327-Discord-Developer-Policy | **未取得・要原典確認** |
| Discord Developer Terms of Service | https://support-dev.discord.com/hc/en-us/articles/8562894815383-Discord-Developer-Terms-of-Service | **未取得・要原典確認** |
| JP-MuseHeart-MusicBot レビュー報告書 | https://github.com/warasugitewara/JP-MuseHeart-MusicBot/blob/main/docs/legal-and-refactoring-review.md | 観点と形式の基準 |

---

<a id="appendix-a"></a>

## 9. 付録A 再現手順

リポジトリのルートで `uv sync --locked` を実行した後、各ブロックを**そのままシェルに貼り付けて**実行します。スクリプトをファイルとして保存する必要はありません。
A-1 は `tempfile.TemporaryDirectory()` の中だけに書き込み、終了時に自動で削除します。`data/` には影響しません。A-2 はファイルに書き込みません。

### A-1 R-2（`users.json` の全件消失）

```bash
PYTHONPATH=. uv run python - <<'EOF'
import pathlib, tempfile
import user_store
from cogs.owner import Owner

with tempfile.TemporaryDirectory() as tmp:
    d = pathlib.Path(tmp)
    user_store._USERS_FILE = d / "users.json"
    s = user_store.UserVoiceStore()
    s.set(111, 3); s.set(222, 46)

    entries = Owner._parse_users_json({"version": 1, "data": [{"user_id": "333", "speaker_id": True}]})
    print("parsed:", entries)
    s.import_all(entries)
    print("file:", (d / "users.json").read_text().replace("\n", ""))
    print("reload after import:", user_store.UserVoiceStore()._data)
    for uid in (444, 555, 666):
        s.set(uid, 1)
    print("reload after 3 more saves:", user_store.UserVoiceStore()._data)
EOF
```

最後の行が `reload after 3 more saves: {}` になれば、再現できています。

### A-2 R-4（辞書の正規表現のコスト）

```bash
PYTHONPATH=. uv run python - <<'EOF'
import random, string, time
from text_filter import filter_message, _compile_dict

random.seed(0)
def rw(): return "".join(random.choices(string.ascii_lowercase, k=random.randint(3, 12)))
def jw(): return "".join(random.choices("あいうえおかきくけこさしすせそ東京大阪", k=random.randint(2, 8)))

for n in (100, 1000, 5000):
    d = {}
    while len(d) < n:
        d[rw() if len(d) % 2 else jw()] = "よみ"
    for label, msg in (("ascii2000", "hello world " * 166),
                       ("ja2000", "今日はいい天気ですね" * 200),
                       ("ja4000", "今日はいい天気ですね" * 400)):
        _compile_dict.cache_clear(); filter_message("x", d)  # コンパイルを済ませる
        t = time.perf_counter()
        for _ in range(5):
            filter_message(msg, d)
        print(f"n={n:5d} {label}: {(time.perf_counter() - t) / 5 * 1000:8.1f} ms/msg")
EOF
```

測定値は実行する環境によって変わります。ただし、時間が件数とメッセージ長にほぼ比例して増える傾向は、どの環境でも同じです。

### A-3 R-5 / R-6 / R-1 の根拠になる discord.py のソース

使用中の discord.py 2.7.1（`.venv/lib/python3.11/site-packages/discord/`）の該当箇所です。

| 項目 | ファイル | 内容 |
|---|---|---|
| R-6 | `ext/commands/context.py:551-`（`send_help`） | `bot.help_command` が `None` なら `return None` |
| R-5 | `ext/commands/hybrid.py:455-480` | hybrid コマンドのエラーを `dispatch_error` で `on_command_error` に回す |
| R-1 | `ext/commands/converter.py:470-498` | `guild.get_channel(channel_id)` で引くだけで、権限は確認しない |

---

<a id="appendix-b"></a>

## 10. 付録B MuseHeart 報告書の訂正

MuseHeart の報告書の L-8 には、「日本の個人情報保護法（APPI）上、Discord ユーザーIDは個人識別符号に該当し得ます」とあります。

しかし、個人情報保護法の **「個人識別符号」（法 2 条 2 項）は、政令で定められたものに限られます**。具体的には、DNA・顔・指紋などの身体的特徴をデータにしたものと、旅券番号やマイナンバーなどの公的な番号です。民間のサービスが割り当てる ID は含まれません。

Discord のユーザー ID は、**他の情報と容易に照合して特定の個人を識別できる場合に「個人情報」に当たり得る**、と整理するのが正確です。MuseHeart 報告書の結論（データを適切に管理し、削除の手段を用意する）は変わりませんが、用語は訂正しておくことを勧めます。
