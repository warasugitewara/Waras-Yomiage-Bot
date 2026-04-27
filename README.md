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
apt install -y curl wget git unzip ffmpeg python3 python3-pip python3-venv nano
```

#### 2. Python バージョン確認

```bash
python3 --version
# Python 3.11.x 以上であることを確認
```

#### 3. VOICEVOX ENGINE のインストール

CPU 版（GPU なし）のヘッドレスエンジンを使います。

```bash
mkdir -p /opt && cd /opt

# リリースページから最新の linux-cpu.zip を確認してダウンロード
# https://github.com/VOICEVOX/voicevox_engine/releases
curl -L -o voicevox_engine.zip \
  https://github.com/VOICEVOX/voicevox_engine/releases/latest/download/linux-cpu.zip

unzip voicevox_engine.zip -d voicevox_engine
chmod +x /opt/voicevox_engine/run

# 動作テスト（起動後 Ctrl+C で停止）
/opt/voicevox_engine/run --host 127.0.0.1 --port 50021
# → "Application startup complete." が出れば OK
```

> ⚠️ ダウンロードURLはバージョンにより変わることがあります。  
> うまくいかない場合は [GitHub Releases](https://github.com/VOICEVOX/voicevox_engine/releases) から `linux-cpu.zip` の URL を直接コピーしてください。

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
PREFIX=!                             # コマンドプレフィックス
DEFAULT_SPEAKER=3                    # スピーカーID（3 = ずんだもん ノーマル）
DEFAULT_SPEED=1.0                    # 読み上げ速度（0.5〜2.0）
MAX_TEXT_LENGTH=100                  # 最大読み上げ文字数
```

主要なスピーカーID例：

| ID | キャラクター | スタイル |
|---|---|---|
| 3 | ずんだもん | ノーマル |
| 1 | 四国めたん | ノーマル |
| 2 | 四国めたん | あまあま |
| 8 | 春日部つむぎ | ノーマル |

全スピーカー一覧は起動後に `http://<コンテナIP>:50021/speakers` または `/myvoice list` で確認できます。

#### 6. systemd サービスの登録

```bash
# VOICEVOX ENGINE サービス
cat > /etc/systemd/system/voicevox.service << 'EOF'
[Unit]
Description=VOICEVOX ENGINE
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/voicevox_engine
ExecStart=/opt/voicevox_engine/run --host 127.0.0.1 --port 50021
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
