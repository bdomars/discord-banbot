import logging
import os
import time
from dataclasses import dataclass, field
from typing import TypedDict

import discord
from cachetools import TTLCache

TOKEN = os.environ["DISCORD_TOKEN"]
LOG_CHANNEL_NAME = os.environ.get("DISCORD_LOG_CHANNEL_NAME", "bot-actions")

WINDOW_SECONDS = 8
RETENTION_SECONDS = 2 * 60
MAX_CHANNELS = 3


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default

    return value.strip().lower() not in {"0", "false", "no", "off"}


DRY_RUN = env_bool("DISCORD_DRY_RUN", True)

logger = logging.getLogger("banbot.main")


class AttachmentSummary(TypedDict):
    filename: str
    url: str


class RecentPostEvent(TypedDict):
    timestamp: float
    created_at: str
    guild_id: int
    guild_name: str
    channel_id: int
    channel_name: str
    message_id: int
    content: str
    attachments: list[AttachmentSummary]


@dataclass
class ActiveIncident:
    reported: bool = False
    ban_attempted: bool = False
    deleted_message_ids: set[int] = field(default_factory=set)


recent_user_posts: TTLCache[tuple[int, int], list[RecentPostEvent]] = TTLCache(
    maxsize=50_000,
    ttl=RETENTION_SECONDS,
)
active_incidents: TTLCache[tuple[int, int], ActiveIncident] = TTLCache(
    maxsize=50_000,
    ttl=RETENTION_SECONDS,
)

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True

client = discord.Client(intents=intents)


def user_profile_link(user: discord.abc.User) -> str:
    return f"<@{user.id}>"


def guild_user_key(guild_id: int, user_id: int) -> tuple[int, int]:
    return guild_id, user_id


async def log(guild: discord.Guild, message: str):
    logger.info("[%s:%s] %s", guild.name, guild.id, message)

    log_channel = find_log_channel(guild)

    if log_channel is None:
        return

    try:
        await log_channel.send(
            f"{message}",
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except discord.HTTPException as exc:
        logger.warning("Failed to post log message: %s", exc)


async def send_log_embed(guild: discord.Guild, embed: discord.Embed):
    logger.info("[%s:%s] %s", guild.name, guild.id, embed.title)

    log_channel = find_log_channel(guild)

    if log_channel is None:
        return

    try:
        await log_channel.send(
            embed=embed,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except discord.HTTPException as exc:
        logger.warning("Failed to post log embed: %s", exc)


def find_log_channel(guild: discord.Guild) -> discord.TextChannel | None:
    return discord.utils.get(
        guild.text_channels,
        name=LOG_CHANNEL_NAME,
    )


def check_guild_setup(guild: discord.Guild) -> None:
    bot_member = guild.me
    missing_permissions = []
    has_setup_warning = False

    if not bot_member.guild_permissions.manage_messages:
        missing_permissions.append("Manage Messages")

    if not bot_member.guild_permissions.ban_members:
        missing_permissions.append("Ban Members")

    log_channel = find_log_channel(guild)
    if log_channel is None:
        has_setup_warning = True
        logger.warning(
            "Could not find #%s in %s (%s)",
            LOG_CHANNEL_NAME,
            guild.name,
            guild.id,
        )
    elif not log_channel.permissions_for(bot_member).send_messages:
        missing_permissions.append(f"Send Messages in #{LOG_CHANNEL_NAME}")

    if missing_permissions:
        logger.warning(
            "Missing permissions in %s (%s): %s",
            guild.name,
            guild.id,
            ", ".join(missing_permissions),
        )
    elif not has_setup_warning:
        logger.info(
            "Required permissions are present in %s (%s)",
            guild.name,
            guild.id,
        )


def truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value

    return f"{value[:limit - 3]}..."


def attachment_summary(message: discord.Message) -> list[AttachmentSummary]:
    return [
        {
            "filename": attachment.filename,
            "url": attachment.url,
        }
        for attachment in message.attachments
    ]


async def is_channel_hopping_spam(message: discord.Message) -> bool:
    now = time.monotonic()
    key = guild_user_key(message.guild.id, message.author.id)

    events = recent_user_posts.get(key, [])

    events = [
        event for event in events
        if now - event["timestamp"] <= WINDOW_SECONDS
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

    recent_user_posts[key] = events

    unique_channels = {event["channel_id"] for event in events}

    return len(unique_channels) > MAX_CHANNELS


async def delete_recent_seen_messages(
    guild: discord.Guild,
    user_id: int,
    incident: ActiveIncident,
) -> dict[int, str]:
    events = recent_user_posts.get(guild_user_key(guild.id, user_id), [])
    results: dict[int, str] = {}

    for event in events:
        message_id = event["message_id"]

        if message_id in incident.deleted_message_ids:
            results[message_id] = "already processed"
            continue

        channel = guild.get_channel_or_thread(event["channel_id"])
        if channel is None:
            results[message_id] = "channel not found"
            incident.deleted_message_ids.add(message_id)
            continue

        if not isinstance(
            channel,
            (
                discord.TextChannel,
                discord.Thread,
                discord.VoiceChannel,
                discord.StageChannel,
            ),
        ):
            results[message_id] = "not a message channel"
            incident.deleted_message_ids.add(message_id)
            continue

        try:
            msg = await channel.fetch_message(message_id)
            await msg.delete()
            results[message_id] = "deleted"
            incident.deleted_message_ids.add(message_id)
        except discord.NotFound:
            results[message_id] = "already gone"
            incident.deleted_message_ids.add(message_id)
        except discord.Forbidden:
            results[message_id] = "missing permission"
            logger.warning("Missing permission to delete message")
        except discord.HTTPException as exc:
            results[message_id] = f"failed: {exc}"
            logger.warning("Failed to delete message: %s", exc)

    return results


def format_event_field(
    event: RecentPostEvent,
    value_limit: int,
) -> tuple[str, str]:
    channel_name = event["channel_name"] or str(event["channel_id"])
    name = truncate(f"#{channel_name}", 256)

    content = event.get("content") or "[no text content]"
    lines = [
        f"Created: {event['created_at']}",
        f"Content: {truncate(content, 700)}",
    ]

    attachments = event.get("attachments", [])
    if attachments:
        attachment_lines = []
        for attachment in attachments[:5]:
            filename = truncate(attachment["filename"], 80)
            attachment_lines.append(f"[{filename}]({attachment['url']})")
        if len(attachments) > 5:
            attachment_lines.append(f"...and {len(attachments) - 5} more")
        lines.append(f"Attachments: {', '.join(attachment_lines)}")

    return name, truncate("\n".join(lines), value_limit)


async def log_spam_evidence(
    message: discord.Message,
    reason: str,
):
    events = recent_user_posts.get(
        guild_user_key(message.guild.id, message.author.id),
        [],
    )
    description = (
        f"{user_profile_link(message.author)} ({message.author.id})\n"
        f"Guild: {message.guild.name} ({message.guild.id})\n"
        f"{reason}\n"
        f"Dry run: {DRY_RUN}"
    )

    embed = discord.Embed(
        title="Spam detected",
        description=description,
        color=discord.Color.red(),
    )

    used_chars = len("Spam detected") + len(description)
    omitted_count = 0

    for index, event in enumerate(events):
        name, value = format_event_field(event, 700)
        remaining_chars = 5800 - used_chars - len(name)

        if remaining_chars < 120:
            omitted_count = len(events) - index
            break

        if len(value) > remaining_chars:
            value = truncate(value, remaining_chars)

        embed.add_field(name=name, value=value, inline=False)
        used_chars += len(name) + len(value)

    if omitted_count:
        embed.set_footer(text=f"{omitted_count} additional recent messages omitted")

    await send_log_embed(message.guild, embed)


async def handle_spam(message: discord.Message, incident: ActiveIncident):
    reason = (
        f"Posted in more than {MAX_CHANNELS} channels "
        f"within {WINDOW_SECONDS} seconds"
    )

    logger.info(
        "[SPAM] %s (%s): %s",
        message.author,
        message.author.id,
        reason,
    )

    await delete_recent_seen_messages(
        message.guild,
        message.author.id,
        incident,
    )

    if not incident.reported:
        incident.reported = True
        await log_spam_evidence(message, reason)

    if incident.ban_attempted:
        return

    incident.ban_attempted = True

    if DRY_RUN:
        await log(message.guild, "[DRY_RUN] Dry run, would ban user here")
        return

    try:
        await message.guild.ban(
            message.author,
            reason="Spam detected",
            delete_message_seconds=3600,
        )
    except discord.Forbidden:
        await log(message.guild, "Missing permission to ban user")
    except discord.HTTPException as exc:
        await log(message.guild, f"Failed to ban user: {exc}")


@client.event
async def on_ready():
    logger.info("Logged in as %s", client.user)
    logger.info("Dry run: %s", DRY_RUN)
    logger.info(
        "Detection window: %s seconds; message count threshold: %s",
        WINDOW_SECONDS,
        MAX_CHANNELS,
    )

    for guild in client.guilds:
        check_guild_setup(guild)


@client.event
async def on_guild_join(guild: discord.Guild):
    logger.info("Added to server: %s (%s)", guild.name, guild.id)
    check_guild_setup(guild)


@client.event
async def on_message(message: discord.Message):
    if message.guild is None:
        return

    if message.author.bot:
        return

    key = guild_user_key(message.guild.id, message.author.id)
    is_spam = await is_channel_hopping_spam(message)
    incident = active_incidents.get(key)

    if incident is None:
        if not is_spam:
            return

        incident = ActiveIncident()
        active_incidents[key] = incident

    await handle_spam(message, incident)
    active_incidents[key] = incident


client.run(TOKEN, root_logger=True)
