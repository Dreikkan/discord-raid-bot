from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import discord

from .constants import (
    REMINDER_LOOP_SECONDS,
    REMINDER_MINUTES,
    REMINDER_RETRY_SECONDS,
    STATUS_BENCH,
    STATUS_MAIN,
)
from .text import escape_markdown
from .time_utils import (
    TimeInputError,
    next_daily_event,
    next_weekly_event,
    parse_time_value,
)

log = logging.getLogger(__name__)

_DISCORD_MESSAGE_LIMIT = 2000
_MENTION_CHUNK_LIMIT = 1900


class ReminderService:
    """Weekly/daily configured reminders and legacy per-raid 15-minute pings."""

    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self._task: asyncio.Task[None] | None = None
        self._last_attempt: dict[str, float] = {}
        self._last_configured_attempt: dict[str, float] = {}

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="raid-reminders")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run(self) -> None:
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                await self.check_due_reminders()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Ошибка в планировщике напоминаний")

            await asyncio.sleep(REMINDER_LOOP_SECONDS)

    async def check_due_reminders(self) -> None:
        now = int(time.time())
        await self._cleanup_expired_messages(now)
        configured_guilds = await self.check_configured_reminders(now)

        threshold = REMINDER_MINUTES * 60

        for raid in self.bot.store.all_raids():
            if str(raid.get("guild_id")) in configured_guilds:
                continue
            if raid.get("notification_sent_at"):
                continue

            start_at = int(raid.get("start_at", 0))
            if start_at <= now:
                continue
            if now < start_at - threshold:
                continue

            raid_id = str(raid["id"])
            last_attempt = self._last_attempt.get(raid_id, 0)
            if now - last_attempt < REMINDER_RETRY_SECONDS:
                continue
            self._last_attempt[raid_id] = time.time()

            if await self._send_raid_reminder(raid):
                self.bot.store.mark_notification_sent(raid_id, now)
                self._last_attempt.pop(raid_id, None)

    # -------------------------------------------------- Configured reminders

    async def check_configured_reminders(self, now: int) -> set[str]:
        configured_guilds: set[str] = set()

        for guild_id in list(self.bot.store.data.get("guilds", {})):
            settings = self.bot.store.settings_for(guild_id)
            reminder = settings.get("reminder")
            if not isinstance(reminder, dict):
                continue

            configured_guilds.add(str(guild_id))
            event_at = int(reminder.get("next_event_at", 0))
            fire_at = int(reminder.get("next_fire_at", 0))

            if event_at <= now:
                self._advance_configured_reminder(guild_id, reminder, event_at)
                continue
            if now < fire_at:
                continue

            last_attempt = self._last_configured_attempt.get(str(guild_id), 0)
            if now - last_attempt < REMINDER_RETRY_SECONDS:
                continue
            self._last_configured_attempt[str(guild_id)] = time.time()

            if await self._send_configured_reminder(
                guild_id, reminder, event_at
            ):
                self._advance_configured_reminder(guild_id, reminder, event_at)
                self._last_configured_attempt.pop(str(guild_id), None)

        return configured_guilds

    def _advance_configured_reminder(
        self,
        guild_id: str,
        reminder: dict[str, Any],
        after_ts: int,
    ) -> None:
        try:
            time_value = parse_time_value(str(reminder["time"]))
            if reminder.get("frequency") == "daily":
                next_event_at = next_daily_event(
                    time_value,
                    str(reminder["timezone"]),
                    after_ts=after_ts,
                )
            else:
                next_event_at = next_weekly_event(
                    int(reminder["weekday"]),
                    time_value,
                    str(reminder["timezone"]),
                    after_ts=after_ts,
                )
        except (KeyError, TypeError, ValueError, TimeInputError):
            log.exception("Некорректные настройки напоминания сервера %s", guild_id)
            return

        self.bot.store.advance_reminder(
            guild_id,
            next_event_at=next_event_at,
            next_fire_at=next_event_at - REMINDER_MINUTES * 60,
        )

    async def _send_configured_reminder(
        self,
        guild_id: str,
        reminder: dict[str, Any],
        event_at: int,
    ) -> bool:
        try:
            channel_id = int(reminder["channel_id"])
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(channel_id)
        except (discord.DiscordException, ValueError, TypeError):
            log.exception("Не найден канал для напоминания сервера %s", guild_id)
            return False

        role_id = int(reminder["role_id"])
        description = str(reminder.get("description") or "").strip()

        lines = [f"<@&{role_id}>"]
        if description:
            lines.extend(("", description))
        lines.extend(
            (
                "",
                f"⏰ **Напоминание о рейде**\n"
                f"Начало: <t:{event_at}:t> · <t:{event_at}:R>",
            )
        )

        matching_raid = self._find_matching_raid(guild_id, event_at)
        if matching_raid is not None:
            registrations = matching_raid.get("registrations", {})
            main_ids = [
                user_id
                for user_id, registration in registrations.items()
                if registration.get("status") == STATUS_MAIN
            ]
            bench_ids = [
                user_id
                for user_id, registration in registrations.items()
                if registration.get("status") == STATUS_BENCH
            ]
            if main_ids or bench_ids:
                main_text = " ".join(f"<@{user_id}>" for user_id in main_ids) or "—"
                bench_text = " ".join(f"<@{user_id}>" for user_id in bench_ids) or "—"
                lines.extend(
                    (
                        "",
                        f"**Участники:** {main_text}",
                        f"**Скамья запасных:** {bench_text}",
                    )
                )

        content = "\n".join(lines)
        allowed_mentions = discord.AllowedMentions(
            everyone=False, roles=True, users=True, replied_user=False
        )
        delete_after = int(reminder["delete_after_minutes"]) * 60
        delete_at = int(time.time()) + delete_after

        try:
            for chunk in self._split_content(content):
                message = await channel.send(
                    chunk, allowed_mentions=allowed_mentions
                )
                self.bot.store.schedule_message_deletion(
                    channel_id=channel.id,
                    message_id=message.id,
                    delete_at=delete_at,
                )
        except (discord.DiscordException, ValueError, TypeError):
            log.exception("Не удалось отправить напоминание сервера %s", guild_id)
            return False

        log.info(
            "Напоминание сервера %s отправлено в канал %s",
            guild_id,
            channel.id,
        )
        return True

    def _find_matching_raid(
        self, guild_id: str, event_at: int
    ) -> dict[str, Any] | None:
        candidates = [
            raid
            for raid in self.bot.store.all_raids()
            if str(raid.get("guild_id")) == str(guild_id)
            and abs(int(raid.get("start_at", 0)) - event_at) <= 300
        ]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda raid: abs(int(raid.get("start_at", 0)) - event_at),
        )

    @staticmethod
    def _split_content(content: str, limit: int = _MENTION_CHUNK_LIMIT) -> list[str]:
        chunks: list[str] = []
        remaining = content

        while len(remaining) > limit:
            cut = remaining.rfind("\n", 0, limit)
            if cut <= 0:
                cut = remaining.rfind(" ", 0, limit)
            if cut <= 0:
                cut = limit
            chunk = remaining[:cut].strip()
            if chunk:
                chunks.append(chunk)
            remaining = remaining[cut:].lstrip()

        if remaining.strip():
            chunks.append(remaining.strip())

        return chunks or [content]

    async def _cleanup_expired_messages(self, now: int) -> None:
        for item in self.bot.store.pop_due_deletions(now):
            try:
                channel_id = int(item["channel_id"])
                message_id = int(item["message_id"])
                channel = self.bot.get_channel(channel_id)
                if channel is None:
                    channel = await self.bot.fetch_channel(channel_id)
                message = await channel.fetch_message(message_id)
                await message.delete()
            except (discord.NotFound, discord.Forbidden):
                continue
            except (discord.DiscordException, KeyError, ValueError, TypeError):
                log.exception("Не удалось удалить сообщение напоминания")

    # ------------------------------------------------------ Legacy reminders

    async def _send_raid_reminder(self, raid: dict[str, Any]) -> bool:
        try:
            channel_id = int(raid["channel_id"])
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(channel_id)
        except (discord.DiscordException, ValueError, TypeError):
            log.exception("Не найден канал для напоминания рейда %s", raid.get("id"))
            return False

        registrations = raid.get("registrations", {})
        main_ids = [
            user_id
            for user_id, registration in registrations.items()
            if registration.get("status") == STATUS_MAIN
        ]
        bench_ids = [
            user_id
            for user_id, registration in registrations.items()
            if registration.get("status") == STATUS_BENCH
        ]

        title = escape_markdown(raid.get("title") or "Рейд")
        start_at = int(raid["start_at"])
        header = (
            f"⏰ **Напоминание о рейде «{title}»**\n"
            f"Начало: <t:{start_at}:t> · <t:{start_at}:R>"
        )
        main_text = " ".join(f"<@{user_id}>" for user_id in main_ids) or "—"
        bench_text = " ".join(f"<@{user_id}>" for user_id in bench_ids) or "—"
        content = (
            f"{header}\n\n"
            f"**Участники:** {main_text}\n"
            f"**Скамья запасных:** {bench_text}"
        )

        allowed_mentions = discord.AllowedMentions(
            everyone=False, roles=False, users=True, replied_user=False
        )

        try:
            if len(content) <= _DISCORD_MESSAGE_LIMIT:
                await channel.send(content, allowed_mentions=allowed_mentions)
            else:
                await channel.send(header, allowed_mentions=allowed_mentions)
                await self._send_mention_section(
                    channel, "Участники", main_ids, allowed_mentions
                )
                await self._send_mention_section(
                    channel, "Скамья запасных", bench_ids, allowed_mentions
                )
        except (discord.DiscordException, ValueError, TypeError):
            log.exception("Не удалось отправить напоминание рейда %s", raid.get("id"))
            return False

        log.info(
            "Напоминание рейда %s отправлено (основной состав: %s, скамья: %s)",
            raid.get("id"),
            len(main_ids),
            len(bench_ids),
        )
        return True

    async def _send_mention_section(
        self,
        channel: discord.abc.Messageable,
        label: str,
        user_ids: list[str],
        allowed_mentions: discord.AllowedMentions,
    ) -> None:
        if not user_ids:
            await channel.send(
                f"**{label}:** —", allowed_mentions=allowed_mentions
            )
            return

        prefix = f"**{label}:**"
        current = prefix
        for user_id in user_ids:
            mention = f"<@{user_id}>"
            if len(current) + len(mention) + 1 > _MENTION_CHUNK_LIMIT:
                await channel.send(current, allowed_mentions=allowed_mentions)
                current = f"**{label} (продолжение):** {mention}"
                continue
            current = f"{current} {mention}"

        if current.strip():
            await channel.send(current, allowed_mentions=allowed_mentions)
