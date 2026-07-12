import asyncio
import logging
import time
from dataclasses import dataclass, field

import discord


logger = logging.getLogger("banbot.incidents")


@dataclass
class ActiveIncident:
    started_at: float
    last_seen_at: float
    guild_id: int
    guild_name: str
    user_id: int
    user_name: str
    reported: bool = False
    ban_attempted: bool = False
    deleted_message_ids: set[int] = field(default_factory=set)


def guild_user_key(guild_id: int, user_id: int) -> tuple[int, int]:
    return guild_id, user_id


class IncidentTracker:
    def __init__(self, retention_seconds: int, cleanup_interval_seconds: int):
        self.retention_seconds = retention_seconds
        self.cleanup_interval_seconds = cleanup_interval_seconds
        self.active_incidents: dict[tuple[int, int], ActiveIncident] = {}
        self.cleanup_task: asyncio.Task[None] | None = None

    def get(self, guild_id: int, user_id: int) -> ActiveIncident | None:
        return self.active_incidents.get(guild_user_key(guild_id, user_id))

    def set(self, incident: ActiveIncident) -> None:
        self.active_incidents[guild_user_key(incident.guild_id, incident.user_id)] = incident

    def start(self, message: discord.Message) -> ActiveIncident:
        now = time.monotonic()
        incident = ActiveIncident(
            started_at=now,
            last_seen_at=now,
            guild_id=message.guild.id,
            guild_name=message.guild.name,
            user_id=message.author.id,
            user_name=str(message.author),
        )

        self.set(incident)

        logger.info(
            "Incident started: guild=%s (%s) user=%s (%s)",
            incident.guild_name,
            incident.guild_id,
            incident.user_name,
            incident.user_id,
        )

        return incident

    def touch(self, incident: ActiveIncident, message: discord.Message) -> None:
        incident.last_seen_at = time.monotonic()
        incident.guild_id = message.guild.id
        incident.guild_name = message.guild.name
        incident.user_id = message.author.id
        incident.user_name = str(message.author)

    def end_inactive(self) -> None:
        now = time.monotonic()

        for key, incident in list(self.active_incidents.items()):
            quiet_seconds = now - incident.last_seen_at

            if quiet_seconds < self.retention_seconds:
                continue

            duration_seconds = now - incident.started_at
            logger.info(
                "Incident ended: guild=%s (%s) user=%s (%s) duration=%.0fs quiet=%.0fs",
                incident.guild_name,
                incident.guild_id,
                incident.user_name,
                incident.user_id,
                duration_seconds,
                quiet_seconds,
            )
            del self.active_incidents[key]

    async def cleanup_loop(self) -> None:
        while True:
            try:
                self.end_inactive()
            except Exception:
                logger.exception("Incident cleanup failed")

            await asyncio.sleep(self.cleanup_interval_seconds)

    def ensure_cleanup_task(self) -> None:
        if self.cleanup_task is not None and not self.cleanup_task.done():
            return

        self.cleanup_task = asyncio.create_task(self.cleanup_loop())
