import time

import discord
from cachetools import TTLCache

from banbot.config import Settings
from banbot.incidents import guild_user_key
from banbot.types import AttachmentSummary, RecentPostEvent


def attachment_summary(message: discord.Message) -> list[AttachmentSummary]:
    return [
        {
            "filename": attachment.filename,
            "url": attachment.url,
        }
        for attachment in message.attachments
    ]


class ChannelHoppingDetector:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.recent_user_posts: TTLCache[tuple[int, int], list[RecentPostEvent]] = (
            TTLCache(
                maxsize=50_000,
                ttl=settings.retention_seconds,
            )
        )

    async def is_spam(self, message: discord.Message) -> bool:
        now = time.monotonic()
        key = guild_user_key(message.guild.id, message.author.id)

        events = self.recent_user_posts.get(key, [])
        events = [
            event for event in events
            if now - event["timestamp"] <= self.settings.window_seconds
        ]

        events.append({
            "timestamp": now,
            "created_at": message.created_at.isoformat(),
            "guild_id": message.guild.id,
            "guild_name": message.guild.name,
            "channel_id": message.channel.id,
            "channel_name": getattr(message.channel, "name", str(message.channel.id)),
            "message_id": message.id,
            "content": message.content,
            "attachments": attachment_summary(message),
        })

        self.recent_user_posts[key] = events

        unique_channels = {event["channel_id"] for event in events}

        return len(unique_channels) > self.settings.max_channels
