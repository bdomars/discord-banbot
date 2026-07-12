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

Enable the privileged **Message Content Intent** for the bot in the Discord
Developer Portal. Banbot uses it to include the deleted spam messages in the
admin log when a user is detected.

Banbot logs actions to a channel named `bot-actions` in each Discord server.
You can change the expected channel name:

```bash
export DISCORD_LOG_CHANNEL_NAME=bot-actions
```

Dry-run mode defaults to enabled. Disable it only when the bot should actually ban users:

```bash
export DISCORD_DRY_RUN=false
```

The web UI listens on port `8080` by default and uses Discord OAuth. Create an
OAuth2 application in the Discord Developer Portal and add a redirect URI that
matches `BANBOT_PUBLIC_BASE_URL` plus `/oauth/callback`, for example
`http://localhost:8080/oauth/callback`.

```bash
export DISCORD_CLIENT_ID=your_oauth_client_id
export DISCORD_CLIENT_SECRET=your_oauth_client_secret
export BANBOT_PUBLIC_BASE_URL=http://localhost:8080
```

For local HTTPS testing without a proxy, generate a self-signed certificate and
point Banbot at it:

```bash
./gen-test-certs.sh

export BANBOT_PUBLIC_BASE_URL=https://localhost:8443
export DISCORD_OAUTH_REDIRECT_URI=https://localhost:8443/oauth/callback
export BANBOT_WEB_PORT=8443
export BANBOT_TLS_CERT_FILE=./certs/localhost.crt
export BANBOT_TLS_KEY_FILE=./certs/localhost.key
```

Run the bot:

```bash
uv run python -m banbot.main
```

Dry-run mode accepts `false`, `0`, `no`, or `off` to disable it; any other set value keeps it enabled.

## Install on Kubernetes

Create a Secret with the bot configuration:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: banbot-config
type: Opaque
stringData:
  DISCORD_TOKEN: your_bot_token
  DISCORD_CLIENT_ID: your_oauth_client_id
  DISCORD_CLIENT_SECRET: your_oauth_client_secret
  BANBOT_PUBLIC_BASE_URL: https://banbot.example.com
  DISCORD_LOG_CHANNEL_NAME: bot-actions
  DISCORD_DRY_RUN: "true"
```

Apply the Secret, then deploy the sample Kustomize configuration:

```bash
kubectl apply -f banbot-secret.yaml
kubectl apply -k 'https://github.com/bdomars/discord-banbot//k8s?ref=main'
```

Create a channel with the configured `DISCORD_LOG_CHANNEL_NAME` in each server
where Banbot should post admin logs.
