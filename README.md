# 🎙️ Waras-Yomiage-Bot

VOICEVOX を使ったローカル完結型 Discord 読み上げBot。

**コンセプト: シンプル・高速・直感的・エコ**

外部 TTS サービスに依存せず、VOICEVOX ENGINE をローカルで動かすことで無駄な遅延を削減し、高いパフォーマンスを実現します。

---

## 必要なもの

| ツール | バージョン |
|---|---|
| Python | 3.11 以上 |
| FFmpeg | 最新安定版 |
| VOICEVOX ENGINE | 最新版 |

---

## 🖥️ Proxmox LXC 環境構築（完全手順）

### コンテナ作成（Proxmox Web UI）

#### 推奨リソース

| 項目 | 推奨値 | 最小値 | 備考 |
|---|---|---|---|
| CPU | 2 vCPU | 1 vCPU | VOICEVOX 合成は CPU 負荷が高め。1コアだと合成に時間がかかる場合がある |
| RAM | 2048 MB | 1024 MB | ENGINE 起動時ピーク ~800MB + Python Bot ~150MB + OS |
| Swap | 512 MB | 0 MB | モデル読み込み時のバッファとして推奨 |
| Disk | 10 GB | 6 GB | OS ~3GB・ENGINE ~2GB・ログ/余裕分 |
| ネットワーク | bridge (vmbr0) | — | Discord への外部通信が必須 |
| 回線速度（上り） | 1 Mbps (0.125 MB/s) 以上 | 0.5 Mbps | Discord 音声は Opus 64kbps ≈ 0.008 MB/s。余裕を持って 1 Mbps 推奨 |
| 回線速度（下り） | 1 Mbps (0.125 MB/s) 以上 | 0.5 Mbps | API・WebSocket 通信のみ。帯域はほぼ消費しない |

#### 手順

1. Proxmox Web UI → **ノード** → **local（またはストレージ）** → **CT Templates**  
   「Templates」ボタン → `debian-13-standard` を検索して **Download**
2. **Create CT** をクリックし、以下を設定：

   | タブ | 設定項目 | 値 |
   |---|---|---|
   | General | Hostname | `yomiage-bot`（任意） |
   | General | Password | root パスワード |
   | General | Unprivileged container | ✅ ON |
   | Template | Template | `debian-13-standard_*.tar.zst` |
   | Disks | Disk size | `10` GB |
   | CPU | Cores | `2` |
   | Memory | Memory | `2048` MB |
   | Memory | Swap | `512` MB |
   | Network | IPv4 | DHCP または固定IP |
   | DNS | DNS | デフォルトのまま |

3. **Finish** → コンテナを選択して **Start**

---

### コンテナ内セットアップ

Proxmox の **Console** タブ、または SSH (`ssh root@<コンテナIP>`) で接続して作業します。

#### 1. システム更新 & 必須ツール導入

```bash
apt update && apt upgrade -y
apt install -y curl wget git p7zip-full ffmpeg python3 python3-pip python3-venv nano
```

#### 2. Python バージョン確認

```bash
python3 --version
# Python 3.11.x 以上であることを確認
```

#### 3. VOICEVOX ENGINE のインストール

CPU 版（GPU なし）のヘッドレスエンジンを使います。  
最新版は **7z 分割形式**（`.7z.001`, `.7z.002`, ...）で配布されているため、`p7zip-full` で展開します。

```bash
mkdir -p /opt/voicevox_dl && cd /opt/voicevox_dl

# バージョンを変数にセット（必要に応じて書き換えてください）
# 最新版は https://github.com/VOICEVOX/voicevox_engine/releases で確認
VVOX_VER="0.25.1"
BASE_URL="https://github.com/VOICEVOX/voicevox_engine/releases/download/${VVOX_VER}/voicevox_engine-linux-cpu-x64-${VVOX_VER}"

# 分割ファイルをすべてダウンロード（存在するパートを順に取得、404 で終了）
n=1
while true; do
  part=$(printf "%03d" $n)
  echo "Downloading part ${part} ..."
  curl -f -L -o "voicevox_engine.7z.${part}" "${BASE_URL}.7z.${part}" || break
  n=$((n + 1))
done

# 分割 7z を展開（/opt/voicevox_engine に展開される）
7za x voicevox_engine.7z.001 -o/opt

# 展開先ディレクトリ名をバージョンに関係なく統一
mv /opt/voicevox_engine-linux-cpu-x64-* /opt/voicevox_engine 2>/dev/null || true
chmod +x /opt/voicevox_engine/linux-cpu-x64/run

# ダウンロード用ディレクトリを削除
cd /opt && rm -rf /opt/voicevox_dl

# 動作テスト（起動後 Ctrl+C で停止）
cd /opt/voicevox_engine/linux-cpu-x64
./run --host 127.0.0.1 --port 50021
# → "Application startup complete." が出れば OK
```

> ℹ️ バージョンアップ時は `VVOX_VER` の値を書き換えて同じ手順を実行してください。  
> リリース一覧: [GitHub Releases](https://github.com/VOICEVOX/voicevox_engine/releases)

#### 4. Bot のセットアップ

```bash
cd /opt
git clone https://github.com/warasugitewara/Waras-Yomiage-Bot.git
cd Waras-Yomiage-Bot

# 仮想環境を作成して依存パッケージをインストール
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 設定ファイルを作成
cp .env.example .env
nano .env
```

#### 5. `.env` の設定

```env
DISCORD_TOKEN=your_token_here        # Discord Bot Token（必須）
VOICEVOX_URL=http://localhost:50021  # VOICEVOX ENGINE の URL
PREFIX=!y                            # コマンドプレフィックス
DEFAULT_SPEAKER=3                    # スピーカーID（3 = ずんだもん ノーマル）
DEFAULT_SPEED=1.0                    # 読み上げ速度（0.5〜2.0）
MAX_TEXT_LENGTH=100                  # 最大読み上げ文字数
# GUILD_ID=123456789012345678        # スラッシュコマンドをギルド限定で即時同期（任意）
# ERROR_WEBHOOK_URL=https://discord.com/api/webhooks/...  # Webhook 通知（任意）
# OWNER_IDS=811515262238064640       # オーナーユーザーID（カンマ区切りで複数可）（任意）
# BOT_STATUS=online                  # ステータス: online / idle / dnd / invisible（任意）
# HEALTH_ENABLED=true                # /health コマンドを有効化（デフォルト: 無効）
```

主要なスピーカーID例：

| キャラクター | スタイル: ID |
|---|---|
| ずんだもん | ノーマル: `3` / あまあま: `1` / ツンツン: `7` / セクシー: `5` / ささやき: `22` / ヒソヒソ: `38` / ヘロヘロ: `75` / なみだめ: `76` |
| 四国めたん | ノーマル: `2` / あまあま: `0` / ツンツン: `6` / セクシー: `4` / ささやき: `36` / ヒソヒソ: `37` |
| 春日部つむぎ | ノーマル: `8` |
| 雨晴はう | ノーマル: `10` |
| 波音リツ | ノーマル: `9` / クイーン: `65` |
| 玄野武宏 | ノーマル: `11` / 喜び: `39` / ツンギレ: `40` / 悲しみ: `41` |
| 白上虎太郎 | ふつう: `12` / わーい: `32` / びくびく: `33` / おこ: `34` / びえーん: `35` |
| 青山龍星 | ノーマル: `13` / 熱血: `81` / 不機嫌: `82` / 喜び: `83` / しっとり: `84` / かなしみ: `85` / 囁き: `86` |
| 冥鳴ひまり | ノーマル: `14` |
| 九州そら | ノーマル: `16` / あまあま: `15` / ツンツン: `18` / セクシー: `17` / ささやき: `19` |
| もち子さん | ノーマル: `20` / セクシー／あん子: `66` / 泣き: `77` / 怒り: `78` / 喜び: `79` / のんびり: `80` |
| 剣崎雌雄 | ノーマル: `21` |
| WhiteCUL | ノーマル: `23` / たのしい: `24` / かなしい: `25` / びえーん: `26` |
| 後鬼 | 人間ver.: `27` / ぬいぐるみver.: `28` / 人間（怒り）ver.: `87` / 鬼ver.: `88` |
| No.7 | ノーマル: `29` / アナウンス: `30` / 読み聞かせ: `31` |
| ちび式じい | ノーマル: `42` |
| 櫻歌ミコ | ノーマル: `43` / 第二形態: `44` / ロリ: `45` |
| 小夜/SAYO | ノーマル: `46` |
| ナースロボ＿タイプＴ | ノーマル: `47` / 楽々: `48` / 恐怖: `49` / 内緒話: `50` |
| †聖騎士 紅桜† | ノーマル: `51` |
| 雀松朱司 | ノーマル: `52` |
| 麒ヶ島宗麟 | ノーマル: `53` |
| 春歌ナナ | ノーマル: `54` |
| 猫使アル | ノーマル: `55` / おちつき: `56` / うきうき: `57` / つよつよ: `110` / へろへろ: `111` |
| 猫使ビィ | ノーマル: `58` / おちつき: `59` / 人見知り: `60` / つよつよ: `112` |
| 中国うさぎ | ノーマル: `61` / おどろき: `62` / こわがり: `63` / へろへろ: `64` |
| 栗田まろん | ノーマル: `67` |
| あいえるたん | ノーマル: `68` |
| 満別花丸 | ノーマル: `69` / 元気: `70` / ささやき: `71` / ぶりっ子: `72` / ボーイ: `73` |
| 琴詠ニア | ノーマル: `74` |
| Voidoll | ノーマル: `89` |
| ぞん子 | ノーマル: `90` / 低血圧: `91` / 覚醒: `92` / 実況風: `93` |
| 中部つるぎ | ノーマル: `94` / 怒り: `95` / ヒソヒソ: `96` / おどおど: `97` / 絶望と敗北: `98` |
| 離途 | ノーマル: `99` / シリアス: `101` |
| 黒沢冴白 | ノーマル: `100` |
| ユーレイちゃん | ノーマル: `102` / 甘々: `103` / 哀しみ: `104` / ささやき: `105` / ツクモちゃん: `106` |
| 東北ずん子 | ノーマル: `107` |
| 東北きりたん | ノーマル: `108` |
| 東北イタコ | ノーマル: `109` |
| あんこもん | ノーマル: `113` / つよつよ: `114` / よわよわ: `115` / けだるげ: `116` / ささやき: `117` |

> 💡 全スピーカー・スタイル一覧は `/myvoice list` または `http://<コンテナIP>:50021/speakers` で確認できます。

#### 6. systemd サービスの登録

```bash
# VOICEVOX ENGINE サービス
cat > /etc/systemd/system/voicevox.service << 'EOF'
[Unit]
Description=VOICEVOX ENGINE
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/voicevox_engine/linux-cpu-x64
ExecStart=/opt/voicevox_engine/linux-cpu-x64/run --host 127.0.0.1 --port 50021
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Yomiage Bot サービス
cat > /etc/systemd/system/yomiage-bot.service << 'EOF'
[Unit]
Description=Waras Yomiage Bot
After=voicevox.service
Requires=voicevox.service

[Service]
Type=simple
WorkingDirectory=/opt/Waras-Yomiage-Bot
ExecStart=/opt/Waras-Yomiage-Bot/.venv/bin/python bot.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# 有効化して起動
systemctl daemon-reload
systemctl enable --now voicevox
systemctl enable --now yomiage-bot
```

#### 7. 動作確認

```bash
# サービス状態の確認
systemctl status voicevox
systemctl status yomiage-bot

# リアルタイムログ
journalctl -u yomiage-bot -f

# VOICEVOX ENGINE が応答するか確認
curl http://localhost:50021/version
```

---

## セットアップ（ローカル・その他環境）

### 1. VOICEVOX ENGINE の起動

VOICEVOX ENGINE はGUIなしで動作するサーバーです。  
[Releases](https://github.com/VOICEVOX/voicevox_engine/releases) から `linux-cpu.zip`（CPUのみの場合）をダウンロードして展開します。

```bash
./run --host 127.0.0.1 --port 50021
```

---

### 2. Bot のセットアップ

```bash
git clone https://github.com/warasugitewara/Waras-Yomiage-Bot.git
cd Waras-Yomiage-Bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# .env を編集して DISCORD_TOKEN を設定
```

---

### 3. Bot の起動

```bash
source .venv/bin/activate
python bot.py
```

---

## コマンド一覧

prefix（デフォルト `!`）と スラッシュコマンド（`/`）の両方に対応しています。

### 基本

| コマンド | 説明 |
|---|---|
| `!join` / `/join` | 実行者のVCに参加し、現在のテキストchを読み上げ対象に自動追加。接続時に「接続しました」と読み上げ |
| `!leave` / `/leave` | VCから退出し、全設定をリセット（エイリアス: `!quit`, `!stop`, `!bye`） |
| `!skip` / `/skip` | 現在再生中の読み上げをスキップ |

### ユーティリティ

| コマンド | 説明 |
|---|---|
| `!help` / `/help` | コマンド一覧を表示。`/help join` のように引数でコマンド詳細も表示 |
| `!about` / `/about` | ボット情報（バージョン・エンジン・リポジトリ）を表示（エイリアス: `!status`） |
| `!ping` / `/ping` | WebSocket 遅延と応答時間を表示 |
| `!health` / `/health` | バージョン・Ping・サーバー数・メモリ・CPU・ネットワーク等を表示（`HEALTH_ENABLED=true` のみ使用可） |

### 音声設定（ユーザー個別）

| コマンド | 説明 |
|---|---|
| `!myvoice set <ID>` / `/myvoice set <ID>` | 自分の読み上げボイスをIDで設定 |
| `!myvoice list` / `/myvoice list` | 利用可能なスピーカー一覧をIDつきで表示 |
| `!myvoice info` / `/myvoice info` | 現在の自分のボイス設定を確認 |
| `!myvoice reset` / `/myvoice reset` | デフォルト（ずんだもん ノーマル）に戻す |
| `!voice <ID>` / `/voice <ID>` | `!myvoice set` の短縮形 |
| `!speed <値>` / `/speed <値>` | サーバー全体の読み上げ速度を変更（0.5〜2.0） |

> 💡 ボイス設定はユーザーごとに独立しています。未設定のユーザーは **ずんだもん ノーマル（ID: 3）** が使われます。

### 管理者向け

| コマンド | 権限 | 説明 |
|---|---|---|
| `!reload_speakers` / `/reload_speakers` | サーバー管理 | VOICEVOXのスピーカー情報キャッシュを再取得（ENGINE更新後などに使用） |

### オーナー向け

オーナーは `.env` の `OWNER_IDS` で登録したユーザーのみ使用できます。未設定の場合は使用不可です。

| コマンド | 説明 |
|---|---|
| `!owner export_users` / `/owner export_users` | 全ユーザーのボイス設定をJSONファイルとしてエクスポート |
| `!owner import_users` / `/owner import_users` | JSONファイルを添付してユーザーのボイス設定をインポート（デフォルト: マージ） |
| `!owner import_users true` / `/owner import_users replace:True` | 既存設定を全置換してインポート |

#### ユーザー設定 JSON フォーマット

```json
{
  "version": 1,
  "data": [
    { "user_id": "811515262238064640", "speaker_id": 46 },
    { "user_id": "987654321098765432", "speaker_id": 3  }
  ]
}
```

- `user_id`: Discord ユーザーID（数字文字列）
- `speaker_id`: VOICEVOX スピーカーID（整数）
- インポート時に不正なエントリ（user_id が数字以外、speaker_id が整数以外）は自動スキップされます

### チャンネル管理

| コマンド | 説明 |
|---|---|
| `!listen add [#ch]` / `/listen add [ch]` | 読み上げチャンネルを追加（省略時は現在のch） |
| `!listen remove [#ch]` / `/listen remove [ch]` | 読み上げチャンネルから削除 |
| `!listen list` / `/listen list` | 登録済みチャンネルを一覧表示 |

### 読み替え辞書

辞書はサーバーごとに独立しています。

| コマンド | 説明 |
|---|---|
| `!dict add <単語> <読み>` / `/dict add` | 読み替えを追加（例: `!dict add w わら`） |
| `!dict remove <単語>` / `/dict remove` | 読み替えを削除 |
| `!dict list` / `/dict list` | 辞書の一覧を表示 |
| `!dict export` / `/dict export` | 辞書をJSONファイルとしてダウンロード |
| `!dict import` / `/dict import` | JSONファイルを添付して辞書をインポート（デフォルト: 既存にマージ） |
| `!dict import true` / `/dict import replace:True` | 既存辞書を全置換してインポート |

#### 辞書 JSON フォーマット

エクスポートされるファイル形式：

```json
{
  "version": 1,
  "data": [
    { "word": "fk",    "reading": "ふぁっきゅー" },
    { "word": "Copilot",    "reading": "こぱいろっと" },
    { "word": "github","reading": "ぎっとはぶ"   }
  ]
}
```

インポート時は以下の3形式に対応しています：

| フォーマット | 条件 |
|---|---|
| **本Bot形式** | `data` 配列の要素が `word` / `reading` キーを持つ |
| **kuroneko TTS Bot 形式** | `data` 配列の要素が `before` / `after` キーを持つ |
| **シンプル形式** | `{"単語": "読み", ...}` のフラットなオブジェクト |

> 💡 kuroneko TTS Bot の辞書エクスポートファイルをそのままインポートできます。

---

## VC 参加時の動作

- `/join` 実行時にボットは自動的に **スピーカーミュート（デフ）状態** で参加します  
  Discord UI でヘッドホンに × アイコンが表示され、ボットがマイク入力を一切受け取らないことがわかります
- TTS の音声送信（読み上げ再生）はデフ状態でも問題なく動作します
- VCに人間が **誰もいなくなってから5秒後** に自動退出します（Bot はカウント外）

---

## Webhook 通知（オプション）

`.env` に `ERROR_WEBHOOK_URL` を設定すると、以下のイベントを Discord Webhook 経由で受け取れます。

| レベル | 通知タイミング |
|---|---|
| 🟢 **info** | Bot 起動完了（ログイン成功） |
| 🟡 **warning** | VOICEVOX 合成エラー・再生エラー・自動退出エラー・スラッシュコマンド同期エラー |
| 🔴 **error** | 起動失敗・Cog 読み込み失敗・コマンドエラー・イベントハンドラ内例外 |

同一通知は **30 秒以内に 1 回のみ送信**（スパム防止）。  
`ERROR_WEBHOOK_URL` が未設定の場合は通知機能ごと無効になります。

### Webhook URL の取得方法

1. Discord サーバーの **チャンネル設定** → **連携サービス** → **ウェブフック**
2. **新しいウェブフック** を作成し、URL をコピー
3. `.env` に貼り付け：  
   ```env
   ERROR_WEBHOOK_URL=https://discord.com/api/webhooks/xxxx/yyyy
   ```

---

## メッセージの前処理

読み上げ前に以下の処理が自動で行われます：

| 処理 | 内容 |
|---|---|
| URL 分類 | URL → サービス名に置換（例: `GitHubリンク`、`YouTubeリンク`、`URLリンク`） |
| メンション除去 | `@user`・`#channel`・ロールメンションを除去 |
| カスタム絵文字 | `<:smile:123>` → `smile` に変換 |
| 読み替え辞書 | サーバーごとの辞書を適用（ASCII 単語は単語境界マッチ） |
| 縦方向スパム圧縮 | 同じ行が改行で **3行以上連続** する場合に最大3行に圧縮 |
| 改行正規化 | 改行（`\n`）を **半角スペース1つ** として扱う（遅延防止） |
| 横方向スパム圧縮 | 同一文字が **5文字以上連続** する場合に3文字に圧縮（`wwwww` → `www`、`！！！！！` → `！！！`） |
| 長文カット | `MAX_TEXT_LENGTH` 超の文章を「以下省略」でカット |

> 💡 縦横どちらのスパムにも対応しています。例えば `w` を20行貼っても「w w w」として読み上げます。

---

## systemd 設定（自動起動）

### VOICEVOX ENGINE

`/etc/systemd/system/voicevox.service`

```ini
[Unit]
Description=VOICEVOX ENGINE
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/opt/voicevox_engine
ExecStart=/opt/voicevox_engine/voicevox_engine --host 127.0.0.1 --port 50021
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

### Yomiage Bot

`/etc/systemd/system/yomiage-bot.service`

```ini
[Unit]
Description=Waras Yomiage Bot
After=voicevox.service
Requires=voicevox.service

[Service]
Type=simple
User=your_user
WorkingDirectory=/opt/Waras-Yomiage-Bot
ExecStart=/usr/bin/python3 /opt/Waras-Yomiage-Bot/bot.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
systemctl enable --now voicevox yomiage-bot
```

---

### thanks for readimg
「最近読み上げbotラグいなぁ」そうだ、自分で作れば良いんだ!! という所から始まりました。
## Super Extream Thanks
[VOICEVOX読み上げbot](https://tts.krnk.org) 今回のbot作成の原因となったbot

## ライセンス

MIT
