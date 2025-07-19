# YoneRai Discord Bot

## Overview
YoneRai is a multi purpose Discord bot that supports music playback, AI powered utilities and various chat tools. Commands can be invoked with the traditional `y!`/`y?` prefix or via Discord slash commands.

## Features
### 🎵 Music
- `y!play` or `/play` to queue songs from links, keywords or attached files.
- Control the queue with `/queue` and buttons for Skip, Shuffle, Loop and Pause.
- Seek, rewind and fast forward tracks.
- Leave the voice channel with `/stop` or `y!stop`.

### 🤖 AI / Tools
- Ask GPT‑4.1 with `y? <question>` or `/gpt <question>`.
- Generate QR codes and barcodes using `/qr` and `/barcode`.
- Render LaTeX formulas with `/tex` or `y!tex`.

### その他
- Translate messages by adding a flag reaction.
- Show user or server info with `/user` and `/server`.
- Roll dice using `/dice` or `y!XdY` (e.g. `2d6`).
- Challenge a friend to `/poker`.
- Bulk delete with `/purge`.
- `/help` displays all available commands.

### 自動通知
- `/news <#channel>` posts hourly Google News articles using excerpts from the article body with a thumbnail.
- `/eew <#channel>` enables real‑time earthquake warnings.
- `/weather <#channel>` posts hourly weather forecasts.

## Installation
1. Install Python 3.11 or later.
2. `pip install -r requirements.txt` to install dependencies.
3. Copy `.env.example` to `.env` and set `DISCORD_BOT_TOKEN` and `OLLAMA_MODEL`.
4. Install `ffmpeg` and run:
   ```bash
   python bot.py
   ```
