import logging
import os
import time

import discord
from cachetools import TTLCache

TOKEN = os.environ["DISCORD_TOKEN"]
LOG_CHANNEL_ID = os.environ.get("DISCORD_LOG_CHANNEL_ID")
LOG_CHANNEL_NAME = "bot-actions"

WINDOW_SECONDS = 15
RETENTION_SECONDS = 2 * 60
MAX_CHANNELS = 3

DRY_RUN = True

logger = logging.getLogger("banbot.main")

recent_user_posts = TTLCache(maxsize=50_000, ttl=RETENTION_SECONDS)

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = False

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
        "channel_id": message.channel.id,
        "message_id": message.id,
    })

    recent_user_posts[user_id] = events

    unique_channels = {event["channel_id"] for event in events}

    return len(unique_channels) > MAX_CHANNELS


async def delete_recent_seen_messages(user_id: int):
    events = recent_user_posts.get(user_id, [])

    for event in events:
        channel = client.get_channel(event["channel_id"])
        if channel is None:
            continue

        try:
            msg = await channel.fetch_message(event["message_id"])
            await msg.delete()
        except discord.NotFound:
            pass
        except discord.Forbidden:
            await log("Missing permission to delete message")
        except discord.HTTPException as exc:
            await log(f"Failed to delete message: {exc}")


async def handle_spam(message: discord.Message):
    reason = (
        f"Posted in more than {MAX_CHANNELS} channels "
        f"within {WINDOW_SECONDS} seconds"
    )

    await log(
        f"[SPAM] {user_profile_link(message.author)} "
        f"({message.author.id}): {reason}"
    )

    await delete_recent_seen_messages(message.author.id)

    if DRY_RUN:
        await log("[DRY_RUN] Dry run, would ban user here")
        return

    try:
        await message.guild.ban(
            message.author,
            reason=reason,
            delete_message_seconds=3600,
        )
    except TypeError:
        await message.guild.ban(
            message.author,
            reason=reason,
            delete_message_days=1,
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
async def on_message(message: discord.Message):
    if message.guild is None:
        return

    if message.author.bot:
        return

    if await is_channel_hopping_spam(message):
        await handle_spam(message)


client.run(TOKEN, root_logger=True)
