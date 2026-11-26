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

log = logging.getLogger(__name__)

_DISCORD_MESSAGE_LIMIT = 2000
_MENTION_CHUNK_LIMIT = 1900


class ReminderService:
    """Sends the 15-minute ping to main-roster and bench players only."""

    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self._task: asyncio.Task[None] | None = None
        self._last_attempt: dict[str, float] = {}

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
        threshold = REMINDER_MINUTES * 60

        for raid in self.bot.store.all_raids():
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

            if await self._send_reminder(raid):
                self.bot.store.mark_notification_sent(raid_id, now)
                self._last_attempt.pop(raid_id, None)

    async def _send_reminder(self, raid: dict[str, Any]) -> bool:
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
