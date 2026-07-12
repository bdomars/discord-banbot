import logging

import discord

from banbot.config import Settings
from banbot.detection import ChannelHoppingDetector
from banbot.incidents import IncidentTracker
from banbot.moderation import Moderator


logger = logging.getLogger("banbot.bot")


def create_client(settings: Settings) -> discord.Client:
    intents = discord.Intents.default()
    intents.guilds = True
    intents.messages = True
    intents.message_content = True

    client = discord.Client(intents=intents)
    detector = ChannelHoppingDetector(settings)
    incidents = IncidentTracker(
        retention_seconds=settings.retention_seconds,
        cleanup_interval_seconds=settings.incident_cleanup_interval_seconds,
    )
    moderator = Moderator(settings, detector)

    @client.event
    async def on_ready():
        logger.info("Logged in as %s", client.user)
        logger.info("Git revision: %s", settings.git_rev)
        logger.info("Dry run: %s", settings.dry_run)
        logger.info(
            "Detection window: %s seconds; message count threshold: %s",
            settings.window_seconds,
            settings.max_channels,
        )
        incidents.ensure_cleanup_task()

        for guild in client.guilds:
            moderator.check_guild_setup(guild)

    @client.event
    async def on_guild_join(guild: discord.Guild):
        logger.info("Added to server: %s (%s)", guild.name, guild.id)
        moderator.check_guild_setup(guild)

    @client.event
    async def on_message(message: discord.Message):
        if message.guild is None:
            return

        if message.author.bot:
            return

        is_spam = await detector.is_spam(message)
        incident = incidents.get(message.guild.id, message.author.id)

        if incident is None:
            if not is_spam:
                return

            incident = incidents.start(message)
        else:
            incidents.touch(incident, message)

        await moderator.handle_spam(message, incident)
        incidents.set(incident)

    return client
