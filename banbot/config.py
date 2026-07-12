import os
from dataclasses import dataclass


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default

    return value.strip().lower() not in {"0", "false", "no", "off"}


@dataclass(frozen=True)
class Settings:
    discord_token: str
    log_channel_name: str
    git_rev: str
    dry_run: bool
    discord_client_id: str | None
    discord_client_secret: str | None
    public_base_url: str
    web_host: str = "0.0.0.0"
    web_port: int = 8080
    tls_cert_file: str | None = None
    tls_key_file: str | None = None
    window_seconds: int = 8
    retention_seconds: int = 2 * 60
    max_channels: int = 3
    incident_cleanup_interval_seconds: int = 5

    @property
    def discord_oauth_redirect_uri(self) -> str:
        configured = os.environ.get("DISCORD_OAUTH_REDIRECT_URI")
        if configured:
            return configured

        return f"{self.public_base_url.rstrip('/')}/oauth/callback"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            discord_token=os.environ["DISCORD_TOKEN"],
            log_channel_name=os.environ.get(
                "DISCORD_LOG_CHANNEL_NAME",
                "bot-actions",
            ),
            git_rev=os.environ.get("BANBOT_GIT_REV", "unknown"),
            dry_run=env_bool("DISCORD_DRY_RUN", True),
            discord_client_id=os.environ.get("DISCORD_CLIENT_ID"),
            discord_client_secret=os.environ.get("DISCORD_CLIENT_SECRET"),
            public_base_url=os.environ.get("BANBOT_PUBLIC_BASE_URL", "http://localhost:8080"),
            web_host=os.environ.get("BANBOT_WEB_HOST", "0.0.0.0"),
            web_port=int(os.environ.get("BANBOT_WEB_PORT", "8080")),
            tls_cert_file=os.environ.get("BANBOT_TLS_CERT_FILE"),
            tls_key_file=os.environ.get("BANBOT_TLS_KEY_FILE"),
        )
