import logging
import os
import time

import discord
from cachetools import TTLCache

TOKEN = os.environ["DISCORD_TOKEN"]
LOG_CHANNEL_ID = os.environ.get("DISCORD_LOG_CHANNEL_ID")
LOG_CHANNEL_NAME = os.environ.get("DISCORD_LOG_CHANNEL_NAME", "bot-actions")

WINDOW_SECONDS = 5
RETENTION_SECONDS = 2 * 60
MAX_CHANNELS = 3


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default

    return value.strip().lower() not in {"0", "false", "no", "off"}


DRY_RUN = env_bool("DISCORD_DRY_RUN", True)

logger = logging.getLogger("banbot.main")

recent_user_posts = TTLCache(maxsize=50_000, ttl=RETENTION_SECONDS)

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True

client = discord.Client(intents=intents)
log_channel = None


def user_profile_link(user: discord.abc.User) -> str:
    return f"<@{user.id}>"


async def log(message: str):
    logger.info(message)

    if log_channel is None:
        return

    try:
        await log_channel.send(
            f"{message}",
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except discord.HTTPException as exc:
        logger.warning("Failed to post log message: %s", exc)


async def send_log_embed(embed: discord.Embed):
    logger.info("%s", embed.title)

    if log_channel is None:
        return

    try:
        await log_channel.send(
            embed=embed,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except discord.HTTPException as exc:
        logger.warning("Failed to post log embed: %s", exc)


def find_log_channel():
    if LOG_CHANNEL_ID is not None:
        try:
            return client.get_channel(int(LOG_CHANNEL_ID))
        except ValueError:
            logger.warning("DISCORD_LOG_CHANNEL_ID must be a numeric channel ID")
            return None

    return discord.utils.get(
        client.get_all_channels(),
        name=LOG_CHANNEL_NAME,
    )


def truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value

    return f"{value[:limit - 3]}..."


def attachment_summary(message: discord.Message) -> list[dict[str, str]]:
    return [
        {
            "filename": attachment.filename,
            "url": attachment.url,
        }
        for attachment in message.attachments
    ]


async def is_channel_hopping_spam(message: discord.Message) -> bool:
    now = time.monotonic()
    user_id = message.author.id

    events = recent_user_posts.get(user_id, [])

    events = [
        event for event in events
        if now - event["timestamp"] <= WINDOW_SECONDS
    ]

    events.append({
        "timestamp": now,
        "created_at": message.created_at.isoformat(),
        "channel_id": message.channel.id,
        "channel_name": getattr(message.channel, "name", str(message.channel.id)),
        "message_id": message.id,
        "content": message.content,
        "attachments": attachment_summary(message),
    })

    recent_user_posts[user_id] = events

    unique_channels = {event["channel_id"] for event in events}

    return len(unique_channels) > MAX_CHANNELS


async def delete_recent_seen_messages(user_id: int):
    events = recent_user_posts.get(user_id, [])
    results = {}

    for event in events:
        channel = client.get_channel(event["channel_id"])
        if channel is None:
            results[event["message_id"]] = "channel not found"
            continue

        try:
            msg = await channel.fetch_message(event["message_id"])
            await msg.delete()
            results[event["message_id"]] = "deleted"
        except discord.NotFound:
            results[event["message_id"]] = "already gone"
        except discord.Forbidden:
            results[event["message_id"]] = "missing permission"
            logger.warning("Missing permission to delete message")
        except discord.HTTPException as exc:
            results[event["message_id"]] = f"failed: {exc}"
            logger.warning("Failed to delete message: %s", exc)

    return results


def format_event_field(
    event: dict,
    deletion_result: str,
    value_limit: int,
) -> tuple[str, str]:
    channel_name = event.get("channel_name") or str(event["channel_id"])
    name = truncate(f"#{channel_name} - {deletion_result}", 256)

    content = event.get("content") or "[no text content]"
    lines = [
        f"Created: {event.get('created_at', 'unknown')}",
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


async def log_spam_evidence(message: discord.Message, reason: str, deletion_results: dict):
    events = recent_user_posts.get(message.author.id, [])
    description = (
        f"{user_profile_link(message.author)} ({message.author.id})\n"
        f"{reason}\n"
        f"Dry run: {DRY_RUN}"
    )

    embed = discord.Embed(
        title="Spam detected",
        description=description,
        color=discord.Color.red(),
    )

    used_chars = len(embed.title) + len(description)
    omitted_count = 0

    for index, event in enumerate(events):
        result = deletion_results.get(event["message_id"], "not processed")
        name, value = format_event_field(event, result, 700)
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

    await send_log_embed(embed)


async def handle_spam(message: discord.Message):
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

    deletion_results = await delete_recent_seen_messages(message.author.id)
    await log_spam_evidence(message, reason, deletion_results)

    if DRY_RUN:
        await log("[DRY_RUN] Dry run, would ban user here")
        return

    try:
        await message.guild.ban(
            message.author,
            reason="Spam detected",
            delete_message_seconds=3600,
        )
    except discord.Forbidden:
        await log("Missing permission to ban user")
    except discord.HTTPException as exc:
        await log(f"Failed to ban user: {exc}")


@client.event
async def on_ready():
    global log_channel

    log_channel = find_log_channel()

    logger.info("Logged in as %s", client.user)
    logger.info("Dry run: %s", DRY_RUN)

    if log_channel is None:
        logger.warning("Could not find #%s", LOG_CHANNEL_NAME)


@client.event
async def on_guild_join(guild: discord.Guild):
    logger.info("Added to server: %s (%s)", guild.name, guild.id)


@client.event
async def on_message(message: discord.Message):
    if message.guild is None:
        return

    if message.author.bot:
        return

    if await is_channel_hopping_spam(message):
        await handle_spam(message)


client.run(TOKEN, root_logger=True)
