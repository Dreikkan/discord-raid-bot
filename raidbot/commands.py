from __future__ import annotations

import logging
import time
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from .constants import (
    MAX_REMINDER_DELETE_MINUTES,
    MAX_REMINDER_DESCRIPTION_LENGTH,
    MAX_TITLE_LENGTH,
    REMINDER_MINUTES,
    ROLE_LABELS,
    ROLE_ORDER,
    WEEKDAY_LABELS,
)
from .date_picker import RaidDatePickerView
from .time_utils import (
    TimeInputError,
    next_daily_event,
    next_weekly_event,
    parse_time_value,
    parse_timezone,
)

log = logging.getLogger(__name__)

REMINDER_FREQUENCY_CHOICES = [
    app_commands.Choice(name="Ежедневно", value="daily"),
    app_commands.Choice(name="Еженедельно", value="weekly"),
]
REMINDER_WEEKDAY_CHOICES = [
    app_commands.Choice(name=label, value=str(index))
    for index, label in enumerate(WEEKDAY_LABELS)
]


def admin_only(func: Any) -> Any:
    return app_commands.checks.has_permissions(manage_guild=True)(func)


def _next_reminder_times(
    *,
    frequency: str,
    weekday: int | None,
    time_value: Any,
    timezone_text: str,
    now: int,
) -> tuple[int, int]:
    if frequency == "daily":
        event_at = next_daily_event(
            time_value, timezone_text, after_ts=now
        )
    else:
        if weekday is None:
            raise TimeInputError("Для еженедельного напоминания выберите день недели.")
        event_at = next_weekly_event(
            weekday, time_value, timezone_text, after_ts=now
        )

    if event_at - REMINDER_MINUTES * 60 <= now:
        if frequency == "daily":
            event_at = next_daily_event(
                time_value, timezone_text, after_ts=event_at
            )
        else:
            event_at = next_weekly_event(
                int(weekday), time_value, timezone_text, after_ts=event_at
            )

    return event_at, event_at - REMINDER_MINUTES * 60


def _reminder_summary(reminder: dict[str, Any]) -> discord.Embed:
    frequency = (
        "Ежедневно"
        if reminder.get("frequency") == "daily"
        else "Еженедельно"
    )
    schedule = reminder.get("time", "—")
    if reminder.get("frequency") == "weekly":
        weekday = reminder.get("weekday")
        if isinstance(weekday, int) and 0 <= weekday <= 6:
            schedule = f"{WEEKDAY_LABELS[weekday]}, {schedule}"
    delete_after = int(reminder.get("delete_after_minutes", 0))

    embed = discord.Embed(
        title="Напоминание настроено",
        color=discord.Color.green(),
    )
    embed.add_field(name="Частота", value=frequency, inline=True)
    embed.add_field(
        name="Время",
        value=f"{schedule} ({reminder.get('timezone', '—')})",
        inline=True,
    )
    embed.add_field(
        name="Следующее напоминание",
        value=f"<t:{reminder['next_fire_at']}:F> · <t:{reminder['next_fire_at']}:R>",
        inline=False,
    )
    embed.add_field(
        name="Канал", value=f"<#{reminder['channel_id']}>", inline=True
    )
    embed.add_field(
        name="Роль", value=f"<@&{reminder['role_id']}>", inline=True
    )
    embed.add_field(
        name="Автоудаление", value=f"через {delete_after} мин.", inline=True
    )
    description = str(reminder.get("description") or "").strip() or "—"
    if len(description) > 1024:
        description = f"{description[:1023]}…"
    embed.add_field(name="Описание", value=description, inline=False)
    return embed


class RaidCog(commands.Cog):
    def __init__(self, bot: Any) -> None:
        self.bot = bot

    @app_commands.command(
        name="создать",
        description="Открыть календарь и создать новый рейд",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.rename(time_value="время")
    @app_commands.describe(
        time_value="Время начала в формате ЧЧ:ММ, например 20:30"
    )
    @admin_only
    async def create(
        self,
        interaction: discord.Interaction,
        time_value: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)

        if interaction.guild is None or interaction.channel is None:
            await interaction.edit_original_response(
                content="Команду нужно использовать на сервере в текстовом канале.",
                embed=None,
                view=None,
            )
            return

        settings = self.bot.store.settings_for(interaction.guild.id)
        specs = settings.get("specs", [])
        missing_roles = [
            ROLE_LABELS[role]
            for role in ROLE_ORDER
            if not any(spec["role"] == role for spec in specs)
        ]
        if missing_roles:
            log.error(
                "В статическом каталоге нет специализаций для ролей: %s",
                ", ".join(missing_roles),
            )
            await interaction.edit_original_response(
                content=(
                    "❌ В каталоге специализаций отсутствуют роли: "
                    f"**{', '.join(missing_roles)}**. Проверьте "
                    "`config/specializations.json`."
                ),
                embed=None,
                view=None,
            )
            return

        try:
            raid_time = parse_time_value(time_value)
        except TimeInputError as exc:
            await interaction.edit_original_response(
                content=f"❌ {exc}", embed=None, view=None
            )
            return

        try:
            view = RaidDatePickerView(
                bot=self.bot,
                channel=interaction.channel,
                guild_id=interaction.guild.id,
                created_by=interaction.user.id,
                raid_time=raid_time,
                time_text=raid_time.strftime("%H:%M"),
                timezone_text=settings["timezone"],
            )
        except TimeInputError as exc:
            await interaction.edit_original_response(
                content=f"❌ {exc}", embed=None, view=None
            )
            return

        await interaction.edit_original_response(
            embed=view.build_embed(), view=view
        )
        view.message = await interaction.original_response()

    @app_commands.command(
        name="название",
        description="Сохранить название для новых эмбедов",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.rename(title="название")
    @app_commands.describe(title="Заголовок эмбеда рейда")
    @admin_only
    async def set_title(self, interaction: discord.Interaction, title: str) -> None:
        title = title.strip()
        if not title:
            await interaction.response.send_message(
                "Название не может быть пустым.", ephemeral=True
            )
            return
        if "\n" in title or "\r" in title:
            await interaction.response.send_message(
                "Название должно быть в одну строку.", ephemeral=True
            )
            return
        if len(title) > MAX_TITLE_LENGTH:
            await interaction.response.send_message(
                f"Название слишком длинное: максимум {MAX_TITLE_LENGTH} символов.",
                ephemeral=True,
            )
            return

        self.bot.store.set_title(interaction.guild_id, title)
        await interaction.response.send_message(
            f"✅ Название сохранено: **{discord.utils.escape_markdown(title)}**\n"
            "Оно будет использоваться в новых эмбедах.",
            ephemeral=True,
        )

    @app_commands.command(
        name="лимиты",
        description="Сохранить количество мест по ролям",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.rename(tanks="танки", healers="хилы", dps="дд")
    @app_commands.describe(
        tanks="Количество танков в основном составе",
        healers="Количество хилов в основном составе",
        dps="Количество ДД в основном составе",
    )
    @admin_only
    async def set_limits(
        self,
        interaction: discord.Interaction,
        tanks: app_commands.Range[int, 1, 50],
        healers: app_commands.Range[int, 1, 50],
        dps: app_commands.Range[int, 1, 50],
    ) -> None:
        self.bot.store.set_limits(
            interaction.guild_id,
            {"tank": tanks, "heal": healers, "dd": dps},
        )
        await interaction.response.send_message(
            "✅ Лимиты сохранены: "
            f"танки — **{tanks}**, хилы — **{healers}**, ДД — **{dps}**.\n"
            "Они применяются к новым рейдам.",
            ephemeral=True,
        )

    @app_commands.command(
        name="часовой-пояс",
        description="Сохранить часовой пояс для ввода времени",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.rename(timezone="часовой_пояс")
    @app_commands.describe(
        timezone="IANA-название (Europe/Moscow) или смещение (UTC+3)"
    )
    @admin_only
    async def set_timezone(
        self, interaction: discord.Interaction, timezone: str
    ) -> None:
        try:
            canonical, _ = parse_timezone(timezone)
        except TimeInputError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return

        self.bot.store.set_timezone(interaction.guild_id, canonical)
        await interaction.response.send_message(
            f"✅ Часовой пояс сохранён: **{canonical}**.\n"
            "Администратор вводит время в этом поясе, а каждый участник "
            "увидит дату и время в своём локальном времени.",
            ephemeral=True,
        )

    @app_commands.command(
        name="напоминание",
        description="Настроить ежедневное или еженедельное напоминание",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.rename(
        channel="канал",
        frequency="частота",
        weekday="день_недели",
        time_value="время",
        description="описание",
        delete_after_minutes="удалить_через_минут",
        role="роль",
        disable="выключить",
    )
    @app_commands.describe(
        channel="Канал, куда отправлять напоминание",
        frequency="Ежедневное или еженедельное",
        weekday="День недели для еженедельного напоминания",
        time_value="Время начала в формате ЧЧ:ММ, например 20:30",
        description="Текст перед напоминанием",
        delete_after_minutes="Через сколько минут удалить сообщение (1–10080)",
        role="Роль, которую упомянуть перед напоминанием",
        disable="Выключить настроенное напоминание",
    )
    @app_commands.choices(
        frequency=REMINDER_FREQUENCY_CHOICES,
        weekday=REMINDER_WEEKDAY_CHOICES,
    )
    @admin_only
    async def configure_reminder(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
        frequency: str | None = None,
        weekday: str | None = None,
        time_value: str | None = None,
        description: str | None = None,
        delete_after_minutes: int | None = None,
        role: discord.Role | None = None,
        disable: bool = False,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Команду нужно использовать на сервере.", ephemeral=True
            )
            return

        settings = self.bot.store.settings_for(interaction.guild.id)
        current = settings.get("reminder")
        if not isinstance(current, dict):
            current = None

        provided = [
            channel,
            frequency,
            weekday,
            time_value,
            description,
            delete_after_minutes,
            role,
        ]
        any_provided = any(value is not None for value in provided)

        if disable:
            if any_provided:
                await interaction.response.send_message(
                    "❌ Чтобы выключить напоминание, не передавайте другие параметры.",
                    ephemeral=True,
                )
                return
            if current is None:
                await interaction.response.send_message(
                    "Напоминание ещё не настроено.", ephemeral=True
                )
                return

            self.bot.store.disable_reminder(interaction.guild.id)
            await interaction.response.send_message(
                "✅ Напоминание выключено.", ephemeral=True
            )
            return

        if not any_provided:
            if current is not None:
                await interaction.response.send_message(
                    embed=_reminder_summary(current), ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "Напоминание ещё не настроено.\n"
                    "Пример:\n"
                    "`/напоминание канал:#рейды частота:Еженедельно "
                    "день_недели:Среда время:20:30 описание:\"Через 15 минут "
                    "начинается рейд\" удалить_через_минут:60 роль:@Рейд`",
                    ephemeral=True,
                )
            return

        if current is None:
            missing = []
            if channel is None:
                missing.append("канал")
            if frequency is None:
                missing.append("частота")
            if time_value is None:
                missing.append("время")
            if description is None:
                missing.append("описание")
            if delete_after_minutes is None:
                missing.append("удалить_через_минут")
            if role is None:
                missing.append("роль")
            if missing:
                await interaction.response.send_message(
                    "❌ Для первого настройки укажите: "
                    + ", ".join(f"`{name}`" for name in missing)
                    + ".",
                    ephemeral=True,
                )
                return

        target_frequency = frequency or (
            current["frequency"] if current is not None else None
        )
        if target_frequency not in {"daily", "weekly"}:
            await interaction.response.send_message(
                "❌ Укажите частоту: ежедневно или еженедельно.",
                ephemeral=True,
            )
            return

        if weekday is not None and target_frequency == "daily":
            await interaction.response.send_message(
                "❌ Для ежедневного напоминания день недели не нужен.",
                ephemeral=True,
            )
            return

        target_weekday: int | None = None
        if target_frequency == "weekly":
            if weekday is not None:
                try:
                    target_weekday = int(weekday)
                except ValueError:
                    target_weekday = None
            elif current is not None and current.get("frequency") == "weekly":
                target_weekday = int(current["weekday"])

            if target_weekday is None or not 0 <= target_weekday <= 6:
                await interaction.response.send_message(
                    "❌ Для еженедельного напоминания выберите день недели.",
                    ephemeral=True,
                )
                return

        try:
            target_time = (
                parse_time_value(time_value)
                if time_value is not None
                else parse_time_value(str(current["time"]))
            )
        except (TimeInputError, KeyError, TypeError):
            await interaction.response.send_message(
                "❌ Укажите время в формате ЧЧ:ММ, например 20:30.",
                ephemeral=True,
            )
            return

        target_description = (
            description.strip()
            if description is not None
            else (str(current.get("description", "")) if current else "")
        )
        if not target_description:
            await interaction.response.send_message(
                "❌ Добавьте описание напоминания.", ephemeral=True
            )
            return
        if len(target_description) > MAX_REMINDER_DESCRIPTION_LENGTH:
            await interaction.response.send_message(
                "❌ Описание слишком длинное: максимум "
                f"{MAX_REMINDER_DESCRIPTION_LENGTH} символов.",
                ephemeral=True,
            )
            return

        target_delete_after = (
            delete_after_minutes
            if delete_after_minutes is not None
            else (int(current["delete_after_minutes"]) if current else None)
        )
        if target_delete_after is None or not 1 <= target_delete_after <= MAX_REMINDER_DELETE_MINUTES:
            await interaction.response.send_message(
                "❌ Время автоудаления должно быть от 1 до "
                f"{MAX_REMINDER_DELETE_MINUTES} минут.",
                ephemeral=True,
            )
            return

        target_channel = channel
        if target_channel is None and current is not None:
            target_channel = interaction.guild.get_channel(
                int(current["channel_id"])
            )
        if target_channel is None:
            await interaction.response.send_message(
                "❌ Выберите канал для напоминания.", ephemeral=True
            )
            return
        if not isinstance(target_channel, discord.TextChannel):
            await interaction.response.send_message(
                "❌ Напоминание можно отправлять только в текстовый канал.",
                ephemeral=True,
            )
            return
        if interaction.guild.me is not None:
            permissions = target_channel.permissions_for(interaction.guild.me)
            if not permissions.send_messages:
                await interaction.response.send_message(
                    "❌ У бота нет прав на отправку сообщений в канале "
                    f"{target_channel.mention}.",
                    ephemeral=True,
                )
                return

        target_role = role
        if target_role is None and current is not None:
            target_role = interaction.guild.get_role(int(current["role_id"]))
        if target_role is None:
            await interaction.response.send_message(
                "❌ Выберите роль для упоминания.", ephemeral=True
            )
            return

        schedule_changed = (
            current is None
            or frequency is not None
            or weekday is not None
            or time_value is not None
        )
        target_timezone = (
            settings["timezone"]
            if current is None or schedule_changed
            else str(current.get("timezone") or settings["timezone"])
        )
        if schedule_changed:
            try:
                next_event_at, next_fire_at = _next_reminder_times(
                    frequency=target_frequency,
                    weekday=target_weekday,
                    time_value=target_time,
                    timezone_text=target_timezone,
                    now=int(time.time()),
                )
            except TimeInputError as exc:
                await interaction.response.send_message(
                    f"❌ {exc}", ephemeral=True
                )
                return
        else:
            next_event_at = int(current["next_event_at"])
            next_fire_at = int(current["next_fire_at"])

        reminder = {
            "frequency": target_frequency,
            "weekday": target_weekday,
            "time": target_time.strftime("%H:%M"),
            "timezone": target_timezone,
            "channel_id": target_channel.id,
            "delete_after_minutes": int(target_delete_after),
            "role_id": target_role.id,
            "description": target_description,
            "next_event_at": next_event_at,
            "next_fire_at": next_fire_at,
        }

        try:
            saved = self.bot.store.set_reminder_config(
                interaction.guild.id, reminder
            )
        except ValueError:
            await interaction.response.send_message(
                "❌ Не удалось сохранить настройки напоминания.", ephemeral=True
            )
            return

        warning = ""
        if not target_role.mentionable:
            warning = (
                "\n⚠️ Роль не разрешена для упоминания в настройках сервера. "
                "Пинг сработает только при наличии права «Mention @everyone, "
                "@here and All Roles»."
            )

        await interaction.response.send_message(
            content=(
                "Также для этого сервера отключены отдельные персональные "
                "напоминания по каждому рейду, чтобы не было дублей."
                f"{warning}"
            ),
            embed=_reminder_summary(saved),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RaidCog(bot))
