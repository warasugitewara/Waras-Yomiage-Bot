# Waras-Yomiage-Bot: Development & Instruction Guide

## Project Overview
**Waras-Yomiage-Bot** is a high-performance, local-first Discord Text-to-Speech (TTS) bot powered by **VOICEVOX ENGINE**. It is designed for low latency, simplicity, and ease of use in a self-hosted environment (e.g., Proxmox LXC).

### Core Technologies
- **Language:** Python 3.11+
- **Discord API:** `discord.py` (v2.3+) with voice support.
- **TTS Engine:** [VOICEVOX](https://voicevox.hiroshiba.jp/) (local HTTP engine).
- **Audio Processing:** `FFmpeg` (for WAV to PCM conversion).
- **Persistence:** Local JSON storage with atomic writes and backup rotation (`data/*.json`).

### Key Components
- `bot.py`: Main entry point. Orchestrates Cog loading, logging, and bot lifecycle.
- `voicevox.py`: Non-blocking HTTP client for VOICEVOX ENGINE API.
- `text_filter.py`: Pre-processing pipeline for messages (URL classification, spam suppression, dictionary application).
- `user_store.py`: Persistence for per-user settings (speaker IDs).
- `channel_store.py`: Persistence for server-specific settings (monitored channels, word dictionary).
- `cogs/`:
    - `tts.py`: Core logic for VC management, dual-queue (TTSItem & PCM) processing, and audio playback.
    - `owner.py`: Management commands for bot owners.
    - `utility.py`: General user commands (help, ping, etc.).
    - `health.py`: System monitoring (enabled via `HEALTH_ENABLED`).

---

## Building and Running

### Prerequisites
1. **Python 3.11+**
2. **FFmpeg** (installed and in PATH)
3. **VOICEVOX ENGINE** (running locally, default port 50021)

### Setup
1. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
2. **Environment Configuration:**
   Copy `.env.example` to `.env` and configure the following:
   - `DISCORD_TOKEN`: Your Discord bot token.
   - `VOICEVOX_URL`: URL to the VOICEVOX engine (default: `http://localhost:50021`).
   - `GUILD_ID`: (Optional) For immediate slash command synchronization during development.

### Running
```bash
python bot.py
```

---

## Development Conventions

### Code Style & Architecture
- **Cog-Based Design:** Functionality is modularized into Cogs. New features should be implemented as new Cogs or additions to existing ones.
- **Hybrid Commands:** All user-facing commands should support both prefix (`!`) and slash (`/`) styles using `commands.hybrid_command`.
- **Type Hinting:** Use Python type hints extensively for clarity and better IDE support.
- **Asynchronous Patterns:**
    - Use `aiohttp` for all external HTTP calls (see `voicevox.py`).
    - Core TTS logic uses a dual-queue system to decouple synthesis (CPU-bound) from playback (I/O-bound).
- **Persistence:**
    - Use `UserVoiceStore` for global user settings.
    - Use `ChannelStore` and `WordDict` for guild-specific settings.
    - All data should be persisted in the `data/` directory using the atomic write patterns defined in the store files.

### Error Handling & Logging
- Use the `WebhookLogger` (accessed via `self.bot.webhook` in Cogs) to log errors and important events to a Discord channel.
- Avoid raw `print` statements in production logic; prefer the webhook logger or formal logging if added.

### Audio Pipeline
- VOICEVOX generates `24kHz mono` WAV.
- `cogs/tts.py` converts this to `48kHz stereo s16le` PCM using FFmpeg.
- **Optimization:** FFmpeg is configured with `-threads 1` to minimize CPU contention.
- **Memory Efficiency:** PCM data is cached using an LRU cache (`_PCM_CACHE_MAX = 100`) to balance performance and memory usage.

### Text Processing
- **High-Performance Filtering:** `text_filter.py` uses a single-pass compiled regex for dictionary replacements, ensuring $O(M)$ performance regardless of dictionary size.

---

## Instructions for Gemini CLI
When modifying this codebase, always ensure that:
1. **Surgical Updates:** Target specific files and avoid unnecessary refactoring.
2. **Persistence Integrity:** Maintain the atomic write and backup rotation logic when modifying data storage.
3. **Voice Compatibility:** Ensure any changes to audio processing are compatible with Discord's requirements (48kHz stereo s16le).
4. **Command Parity:** Maintain both prefix and slash command support for any new user commands.
5. **Security:** Never expose or hardcode credentials from `.env` in logs or output.
