from __future__ import annotations

import copy
import logging
import time
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from .activities import (
    ActivityError,
    format_schedules,
    next_activity_occurrence,
    parse_schedules,
)
from .constants import (
    MAX_REMINDER_DELETE_MINUTES,
    MAX_REMINDER_DESCRIPTION_LENGTH,
    MAX_TITLE_LENGTH,
    ROLE_LABELS,
    ROLE_ORDER,
)
from .date_picker import RaidDatePickerView
from .time_utils import TimeInputError, parse_time_value, parse_timezone

log = logging.getLogger(__name__)


def admin_only(func: Any) -> Any:
    return app_commands.checks.has_permissions(manage_guild=True)(func)


def _activity_details(
    activity: dict[str, Any],
    settings: dict[str, Any],
    now: int,
) -> str:
    schedules = activity.get("schedules", [])
    channel_id = activity.get("channel_id")
    role_id = activity.get("role_id")
    active = bool(schedules and channel_id and role_id)

    lines = [
        f"**Расписание:** {format_schedules(schedules) if schedules else '—'}",
        f"**Канал:** {f'<#{channel_id}>' if channel_id else 'не задан'}",
        f"**Роль:** {f'<@&{role_id}>' if role_id else 'не задана'}",
        f"**Автоудаление:** через {activity.get('delete_after_minutes', 60)} мин.",
        f"**Статус:** {'активно' if active else 'не настроено'}",
    ]

    if active:
        occurrence = next_activity_occurrence(
            activity,
            str(settings.get("timezone") or "UTC"),
            after_ts=now,
        )
        if occurrence is not None:
            start_at, _ = occurrence
            lines.append(
                f"**Ближайшее начало:** <t:{start_at}:F> · <t:{start_at}:R>"
            )

    description = str(activity.get("description") or "").strip()
    if description:
        lines.extend(("", description))

    value = "\n".join(lines)
    return f"{value[:1023]}…" if len(value) > 1024 else value


def _activity_overview(
    activities: list[dict[str, Any]], settings: dict[str, Any]
) -> discord.Embed:
    now = int(time.time())
    embed = discord.Embed(
        title="Активности",
        description=(
            "Отдельные напоминания, не связанные с эмбедом рейда.\n"
            "Чтобы настроить, укажите название активности и нужные параметры."
        ),
        color=discord.Color.blurple(),
    )

    for activity in activities[:25]:
        embed.add_field(
            name=str(activity["name"])[:256],
            value=_activity_details(activity, settings, now),
            inline=False,
        )

    if not activities:
        embed.description = "Активности ещё не созданы."

    embed.set_footer(
        text="Пример: /активность название:Вечеринка канал:#ивенты роль:@Ивенты"
    )
    return embed


def _single_activity_embed(
    activity: dict[str, Any], settings: dict[str, Any]
) -> discord.Embed:
    now = int(time.time())
    embed = discord.Embed(
        title=str(activity["name"]),
        description=_activity_details(activity, settings, now),
        color=discord.Color.blurple(),
    )
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
        name="активность",
        description="Настроить отдельное напоминание об активности",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.rename(
        name="название",
        description="описание",
        channel="канал",
        role="роль",
        schedule_text="расписание",
        delete_after_minutes="удалить_через_минут",
    )
    @app_commands.describe(
        name="Название активности (без параметров — показать все)",
        description="Текст напоминания об активности",
        channel="Канал для напоминаний",
        role="Роль, которую упомянуть перед напоминанием",
        schedule_text=(
            "Например: «Вторник 20:00-22:00; Суббота 19:00-21:00» "
            "или «Ежедневно 21:00-21:30»"
        ),
        delete_after_minutes="Через сколько минут удалить сообщение (1–10080)",
    )
    @admin_only
    async def configure_activity(
        self,
        interaction: discord.Interaction,
        name: str | None = None,
        description: str | None = None,
        channel: discord.TextChannel | None = None,
        role: discord.Role | None = None,
        schedule_text: str | None = None,
        delete_after_minutes: int | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Команду нужно использовать на сервере.", ephemeral=True
            )
            return

        settings = self.bot.store.settings_for(interaction.guild.id)
        activities = settings.get("activities", [])
        has_config_values = any(
            value is not None
            for value in (
                description,
                channel,
                role,
                schedule_text,
                delete_after_minutes,
            )
        )

        if name is None:
            if has_config_values:
                await interaction.response.send_message(
                    "❌ Укажите название активности.", ephemeral=True
                )
                return
            await interaction.response.send_message(
                embed=_activity_overview(activities, settings),
                ephemeral=True,
            )
            return

        current = self.bot.store.find_activity(interaction.guild.id, name)
        if current is not None:
            activity = copy.deepcopy(current)
        else:
            activity = {
                "name": name.strip(),
                "description": "",
                "channel_id": None,
                "role_id": None,
                "delete_after_minutes": 60,
                "schedules": [],
                "last_sent_event_at": 0,
            }

        if current is not None and not has_config_values:
            await interaction.response.send_message(
                embed=_single_activity_embed(activity, settings),
                ephemeral=True,
            )
            return

        if current is None and schedule_text is None:
            await interaction.response.send_message(
                "❌ Для новой активности укажите расписание. Например:\n"
                "`/активность название:Вечеринка расписание:\"Ежедневно 21:00-21:30\"`",
                ephemeral=True,
            )
            return

        if description is not None:
            clean_description = description.strip()
            if len(clean_description) > MAX_REMINDER_DESCRIPTION_LENGTH:
                await interaction.response.send_message(
                    "❌ Описание слишком длинное: максимум "
                    f"{MAX_REMINDER_DESCRIPTION_LENGTH} символов.",
                    ephemeral=True,
                )
                return
            activity["description"] = clean_description

        if channel is not None:
            if interaction.guild.me is not None:
                permissions = channel.permissions_for(interaction.guild.me)
                if not permissions.send_messages:
                    await interaction.response.send_message(
                        "❌ У бота нет прав на отправку сообщений в канале "
                        f"{channel.mention}.",
                        ephemeral=True,
                    )
                    return
            activity["channel_id"] = channel.id

        if role is not None:
            activity["role_id"] = role.id

        if delete_after_minutes is not None:
            if not 1 <= delete_after_minutes <= MAX_REMINDER_DELETE_MINUTES:
                await interaction.response.send_message(
                    "❌ Время автоудаления должно быть от 1 до "
                    f"{MAX_REMINDER_DELETE_MINUTES} минут.",
                    ephemeral=True,
                )
                return
            activity["delete_after_minutes"] = int(delete_after_minutes)

        if schedule_text is not None:
            try:
                activity["schedules"] = parse_schedules(schedule_text)
            except ActivityError as exc:
                await interaction.response.send_message(
                    f"❌ {exc}", ephemeral=True
                )
                return
            activity["last_sent_event_at"] = 0

        try:
            saved = self.bot.store.save_activity(
                interaction.guild.id, activity
            )
        except ActivityError as exc:
            await interaction.response.send_message(
                f"❌ {exc}", ephemeral=True
            )
            return

        warnings: list[str] = []
        if not saved.get("channel_id") or not saved.get("role_id"):
            warnings.append(
                "Укажите канал и роль, иначе напоминание не отправляется."
            )
        if role is not None and not role.mentionable:
            warnings.append(
                "Роль не разрешена для упоминания в настройках сервера. "
                "Пинг сработает только при наличии права «Mention @everyone, "
                "@here and All Roles»."
            )

        await interaction.response.send_message(
            content="\n".join(f"⚠️ {warning}" for warning in warnings) or None,
            embed=_single_activity_embed(saved, settings),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RaidCog(bot))
