# 🎙️ Waras-Yomiage-Bot

VOICEVOX を使ったローカル完結型 Discord 読み上げBot。

**コンセプト: シンプル・高速・直感的・エコ**

外部 TTS サービスに依存せず、VOICEVOX ENGINE をローカルで動かすことでほぼゼロ遅延を実現します。

---

## 必要なもの

| ツール | バージョン |
|---|---|
| Python | 3.11 以上 |
| FFmpeg | 最新安定版 |
| VOICEVOX ENGINE | 最新版 |

---

## セットアップ

### 1. VOICEVOX ENGINE の起動

VOICEVOX ENGINE はGUIなしで動作するサーバーです。  
[Releases](https://github.com/VOICEVOX/voicevox_engine/releases) から `voicevox_engine_linux-cpu-*.tar.gz`（CPUのみの場合）をダウンロードして展開します。

```bash
# 展開後のディレクトリで
./voicevox_engine --host 127.0.0.1 --port 50021
```

systemd で自動起動する場合は後述の「systemd 設定」を参照してください。

---

### 2. FFmpeg のインストール（Debian）

```bash
apt update && apt install -y ffmpeg
```

---

### 3. Bot のセットアップ

```bash
# リポジトリをクローン
git clone https://github.com/warasugitewara/Waras-Yomiage-Bot.git
cd Waras-Yomiage-Bot

# 依存パッケージをインストール
pip install -r requirements.txt

# .env を作成
cp .env.example .env
# .env を編集して DISCORD_TOKEN を設定
```

---

### 4. `.env` の設定

```env
DISCORD_TOKEN=your_token_here       # Discord Bot Token（必須）
VOICEVOX_URL=http://localhost:50021 # VOICEVOX ENGINE の URL
PREFIX=!y                           # コマンドプレフィックス
DEFAULT_SPEAKER=3                   # スピーカーID（3 = ずんだもん ノーマル）
DEFAULT_SPEED=1.0                   # 読み上げ速度（0.5〜2.0）
MAX_TEXT_LENGTH=100                 # 最大読み上げ文字数
```

主要なスピーカーID例：

| ID | キャラクター | スタイル |
|---|---|---|
| 3 | ずんだもん | ノーマル |
| 1 | 四国めたん | ノーマル |
| 2 | 四国めたん | あまあま |
| 8 | 春日部つむぎ | ノーマル |

全スピーカー一覧は `http://localhost:50021/speakers` で確認できます。

---

### 5. Bot の起動

```bash
python bot.py
```

---

## コマンド一覧

prefix（デフォルト `!`）と スラッシュコマンド（`/`）の両方に対応しています。

### 基本

| コマンド | 説明 |
|---|---|
| `!join` / `/join` | 実行者のVCに参加し、現在のテキストchを読み上げ対象に自動追加 |
| `!leave` / `/leave` | VCから退出し、全設定をリセット |
| `!skip` / `/skip` | 現在再生中の読み上げをスキップ |

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

### 読み上げチャンネル管理

| コマンド | 説明 |
|---|---|
| `!listen add [#ch]` / `/listen add [ch]` | 読み上げチャンネルを追加（省略時は現在のch） |
| `!listen remove [#ch]` / `/listen remove [ch]` | 読み上げチャンネルから削除 |
| `!listen list` / `/listen list` | 登録済みチャンネルを一覧表示 |

### 読み替え辞書

| コマンド | 説明 |
|---|---|
| `!dict add <単語> <読み>` / `/dict add` | 読み替えを追加（例: `!dict add w わら`） |
| `!dict remove <単語>` / `/dict remove` | 読み替えを削除 |
| `!dict list` / `/dict list` | 辞書の一覧を表示 |

---

## メッセージの前処理

読み上げ前に以下の処理が自動で行われます：

- URL → 「URL省略」に置換
- メンション（`@user`, `#channel`）を除去
- カスタム絵文字を名前に変換
- `MAX_TEXT_LENGTH` を超えた文章を「…以下省略」でカット
- 読み替え辞書を適用

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

## ライセンス

MIT
