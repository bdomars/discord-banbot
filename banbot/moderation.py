import logging

import discord

from banbot.config import Settings
from banbot.detection import ChannelHoppingDetector
from banbot.incidents import ActiveIncident, guild_user_key
from banbot.types import RecentPostEvent


logger = logging.getLogger("banbot.moderation")


def user_profile_link(user: discord.abc.User) -> str:
    return f"<@{user.id}>"


def truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value

    return f"{value[:limit - 3]}..."


class Moderator:
    def __init__(self, settings: Settings, detector: ChannelHoppingDetector):
        self.settings = settings
        self.detector = detector

    def find_log_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        return discord.utils.get(
            guild.text_channels,
            name=self.settings.log_channel_name,
        )

    async def log(self, guild: discord.Guild, message: str):
        logger.info("[%s:%s] %s", guild.name, guild.id, message)

        log_channel = self.find_log_channel(guild)

        if log_channel is None:
            return

        try:
            await log_channel.send(
                f"{message}",
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException as exc:
            logger.warning("Failed to post log message: %s", exc)

    async def send_log_embed(self, guild: discord.Guild, embed: discord.Embed):
        logger.info("[%s:%s] %s", guild.name, guild.id, embed.title)

        log_channel = self.find_log_channel(guild)

        if log_channel is None:
            return

        try:
            await log_channel.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException as exc:
            logger.warning("Failed to post log embed: %s", exc)

    def check_guild_setup(self, guild: discord.Guild) -> None:
        bot_member = guild.me
        missing_permissions = []
        has_setup_warning = False

        if not bot_member.guild_permissions.manage_messages:
            missing_permissions.append("Manage Messages")

        if not bot_member.guild_permissions.ban_members:
            missing_permissions.append("Ban Members")

        log_channel = self.find_log_channel(guild)
        if log_channel is None:
            has_setup_warning = True
            logger.warning(
                "Could not find #%s in %s (%s)",
                self.settings.log_channel_name,
                guild.name,
                guild.id,
            )
        elif not log_channel.permissions_for(bot_member).send_messages:
            missing_permissions.append(f"Send Messages in #{self.settings.log_channel_name}")

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

    async def delete_recent_seen_messages(
        self,
        guild: discord.Guild,
        user_id: int,
        incident: ActiveIncident,
    ) -> dict[int, str]:
        events = self.detector.recent_user_posts.get(guild_user_key(guild.id, user_id), [])
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
        self,
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
        self,
        message: discord.Message,
        reason: str,
    ):
        events = self.detector.recent_user_posts.get(
            guild_user_key(message.guild.id, message.author.id),
            [],
        )
        description = (
            f"{user_profile_link(message.author)} ({message.author.id})\n"
            f"Guild: {message.guild.name} ({message.guild.id})\n"
            f"{reason}\n"
            f"Dry run: {self.settings.dry_run}"
        )

        embed = discord.Embed(
            title="Spam detected",
            description=description,
            color=discord.Color.red(),
        )

        used_chars = len("Spam detected") + len(description)
        omitted_count = 0

        for index, event in enumerate(events):
            name, value = self.format_event_field(event, 700)
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

        await self.send_log_embed(message.guild, embed)

    async def handle_spam(self, message: discord.Message, incident: ActiveIncident):
        reason = (
            f"Posted in more than {self.settings.max_channels} channels "
            f"within {self.settings.window_seconds} seconds"
        )

        logger.info(
            "[SPAM] %s (%s): %s",
            message.author,
            message.author.id,
            reason,
        )

        await self.delete_recent_seen_messages(
            message.guild,
            message.author.id,
            incident,
        )

        if not incident.reported:
            incident.reported = True
            await self.log_spam_evidence(message, reason)

        if incident.ban_attempted:
            return

        incident.ban_attempted = True

        if self.settings.dry_run:
            await self.log(message.guild, "[DRY_RUN] Dry run, would ban user here")
            return

        try:
            await message.guild.ban(
                message.author,
                reason="Spam detected",
                delete_message_seconds=3600,
            )
        except discord.Forbidden:
            await self.log(message.guild, "Missing permission to ban user")
        except discord.HTTPException as exc:
            await self.log(message.guild, f"Failed to ban user: {exc}")
