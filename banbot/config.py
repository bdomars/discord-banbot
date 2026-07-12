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
    window_seconds: int = 8
    retention_seconds: int = 2 * 60
    max_channels: int = 3
    incident_cleanup_interval_seconds: int = 5

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
        )
