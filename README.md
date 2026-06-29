# banbot

Discord bot that detects users posting across too many channels in a short time window, deletes the recent messages it saw, and optionally bans the user.

## Setup

Install dependencies with uv:

```bash
uv sync
```

Set the required Discord token:

```bash
export DISCORD_TOKEN=your_bot_token
```

Optionally set the log channel by ID. If omitted, the bot looks for a channel named `bot-actions`:

```bash
export DISCORD_LOG_CHANNEL_ID=123456789012345678
```

Run the bot:

```bash
uv run python banbot.py
```

The bot currently runs in dry-run mode unless `DRY_RUN` is changed in `banbot.py`.
