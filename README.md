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

Optionally set the log channel by ID. If omitted, the bot looks for a channel named `bot-actions`, or the name from `DISCORD_LOG_CHANNEL_NAME`:

```bash
export DISCORD_LOG_CHANNEL_ID=123456789012345678
export DISCORD_LOG_CHANNEL_NAME=bot-actions
```

Dry-run mode defaults to enabled. Disable it only when the bot should actually ban users:

```bash
export DISCORD_DRY_RUN=false
```

Run the bot:

```bash
uv run python banbot.py
```

Dry-run mode accepts `false`, `0`, `no`, or `off` to disable it; any other set value keeps it enabled.
