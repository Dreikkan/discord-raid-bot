from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import discord

from .activities import (
    activity_end_at,
    next_activity_occurrence,
)
from .constants import (
    ACTIVITY_CHECKIN_CUSTOM_ID,
    ACTIVITY_REWARD,
    CURRENCY_EMOJI,
    CURRENCY_NAME,
    RAID_REWARD_BENCH,
    RAID_REWARD_MAIN,
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
    """Sends activity reminders and the 15-minute reminder for raid embeds."""

    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self._task: asyncio.Task[None] | None = None
        self._last_attempt: dict[str, float] = {}
        self._last_activity_attempt: dict[str, float] = {}

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
        self.bot.store.prune_activity_events(now - 24 * 60 * 60)
        await self.check_activity_reminders(now)
        self.check_raid_rewards(now)

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

            if await self._send_raid_reminder(raid):
                self.bot.store.mark_notification_sent(raid_id, now)
                self._last_attempt.pop(raid_id, None)

    def check_raid_rewards(self, now: int) -> None:
        for raid in self.bot.store.all_raids():
            if int(raid.get("start_at", 0)) > now:
                continue
            awards = self.bot.store.award_raid_rewards(
                str(raid["id"]),
                main_amount=RAID_REWARD_MAIN,
                bench_amount=RAID_REWARD_BENCH,
                now=now,
            )
            if awards:
                log.info(
                    "Награды за рейд %s начислены %s участникам",
                    raid.get("id"),
                    len(awards),
                )

    # ----------------------------------------------------------- Activities

    async def check_activity_reminders(self, now: int) -> None:
        for guild_id in list(self.bot.store.data.get("guilds", {})):
            settings = self.bot.store.settings_for(guild_id)
            timezone_text = str(settings.get("timezone") or "UTC")
            activities = settings.get("activities", [])

            for activity in activities:
                if activity.get("channel_id") is None:
                    continue
                if activity.get("role_id") is None:
                    continue
                if not activity.get("schedules"):
                    continue

                last_sent_at = int(activity.get("last_sent_event_at", 0))
                base_ts = max(now, last_sent_at)
                occurrence = next_activity_occurrence(
                    activity, timezone_text, after_ts=base_ts
                )
                if occurrence is None:
                    continue

                start_at, schedule = occurrence
                if now >= start_at:
                    continue
                if now < start_at - REMINDER_MINUTES * 60:
                    continue

                activity_id = str(activity["id"])
                key = f"{guild_id}:{activity_id}"
                last_attempt = self._last_activity_attempt.get(key, 0)
                if now - last_attempt < REMINDER_RETRY_SECONDS:
                    continue
                self._last_activity_attempt[key] = time.time()

                if await self._send_activity_reminder(
                    guild_id=guild_id,
                    activity=activity,
                    schedule=schedule,
                    start_at=start_at,
                    timezone_text=timezone_text,
                ):
                    self.bot.store.mark_activity_sent(
                        guild_id, activity_id, start_at
                    )
                    self._last_activity_attempt.pop(key, None)

    async def _send_activity_reminder(
        self,
        *,
        guild_id: str,
        activity: dict[str, Any],
        schedule: dict[str, Any],
        start_at: int,
        timezone_text: str,
    ) -> bool:
        try:
            channel_id = int(activity["channel_id"])
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(channel_id)
        except (discord.DiscordException, ValueError, TypeError):
            log.exception(
                "Не найден канал активности %s на сервере %s",
                activity.get("id"),
                guild_id,
            )
            return False

        role_id = int(activity["role_id"])
        description = str(activity.get("description") or "").strip()
        name = escape_markdown(activity.get("name") or "Активность")
        end_at = activity_end_at(schedule, timezone_text, start_at)
        end_text = f"<t:{end_at}:t>"
        if str(schedule.get("end", "")) <= str(schedule.get("start", "")):
            end_text = f"{end_text} (<t:{end_at}:D>)"

        lines = [f"<@&{role_id}>"]
        if description:
            lines.extend(("", description))
        lines.extend(
            (
                "",
                f"⏰ **{name}** — через 15 минут",
                f"Начало: <t:{start_at}:t> (<t:{start_at}:R>)",
                f"Окончание: {end_text}",
                f"✅ Отметьтесь кнопкой ниже: +{ACTIVITY_REWARD} "
                f"{CURRENCY_EMOJI} {CURRENCY_NAME}",
            )
        )

        content = "\n".join(lines)
        allowed_mentions = discord.AllowedMentions(
            everyone=False, roles=True, users=False, replied_user=False
        )
        delete_after = int(activity["delete_after_minutes"]) * 60
        delete_at = int(time.time()) + delete_after

        try:
            chunks = self._split_content(content)
            for index, chunk in enumerate(chunks):
                view = (
                    ActivityCheckinView(self.bot)
                    if index == len(chunks) - 1
                    else None
                )
                message = await channel.send(
                    chunk,
                    allowed_mentions=allowed_mentions,
                    view=view,
                )
                self.bot.store.schedule_message_deletion(
                    channel_id=channel.id,
                    message_id=message.id,
                    delete_at=delete_at,
                )
                if view is not None:
                    self.bot.store.register_activity_event(
                        message.id,
                        guild_id=guild_id,
                        activity_id=str(activity["id"]),
                        start_at=start_at,
                        end_at=end_at,
                    )
        except (discord.DiscordException, ValueError, TypeError):
            log.exception(
                "Не удалось отправить напоминание активности %s",
                activity.get("id"),
            )
            return False

        log.info(
            "Напоминание активности %s отправлено в канал %s",
            activity.get("name"),
            channel.id,
        )
        return True

    # ------------------------------------------------------ Raid reminders

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
            f"**Скамья запасных:** {bench_text}\n\n"
            f"🎁 После начала: +{RAID_REWARD_MAIN} основному составу, "
            f"+{RAID_REWARD_BENCH} скамье"
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

    # ------------------------------------------------------- Auto-deletions

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


def _format_amount(value: int) -> str:
    return f"{int(value):,}".replace(",", " ")


class ActivityCheckinView(discord.ui.View):
    """Persistent check-in button under an activity reminder."""

    def __init__(self, bot: Any) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        button = discord.ui.Button(
            label="Я участвую",
            emoji="✅",
            style=discord.ButtonStyle.success,
            custom_id=ACTIVITY_CHECKIN_CUSTOM_ID,
        )
        button.callback = self._check_in  # type: ignore[method-assign]
        self.add_item(button)

    async def _check_in(self, interaction: discord.Interaction) -> None:
        if interaction.message is None:
            await interaction.response.send_message(
                "Не удалось найти сообщение активности.", ephemeral=True
            )
            return

        status, amount, balance = self.bot.store.claim_activity_reward(
            interaction.message.id,
            interaction.user.id,
            amount=ACTIVITY_REWARD,
        )
        if status == "missing":
            embed = discord.Embed(
                title="Событие не найдено",
                description=(
                    "Не удалось найти это событие. Возможно, напоминание "
                    "уже устарело."
                ),
                color=discord.Color.red(),
            )
        elif status == "ended":
            embed = discord.Embed(
                title="Активность завершилась",
                description="Награда за эту активность больше недоступна.",
                color=discord.Color.red(),
            )
        elif status == "already":
            embed = discord.Embed(
                title="Награда уже получена",
                description=(
                    "Вы уже отметились на этой активности.\n\n"
                    f"**Баланс:** {CURRENCY_EMOJI} "
                    f"{_format_amount(balance)} {CURRENCY_NAME}"
                ),
                color=discord.Color.orange(),
            )
        else:
            embed = discord.Embed(
                title="✅ Награда получена",
                description=(
                    f"**+{amount}** {CURRENCY_EMOJI} {CURRENCY_NAME}\n\n"
                    f"**Баланс:** {CURRENCY_EMOJI} "
                    f"{_format_amount(balance)} {CURRENCY_NAME}"
                ),
                color=discord.Color.green(),
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)
