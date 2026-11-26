from __future__ import annotations

import calendar
import functools
import logging
import time
from datetime import date, datetime, time as time_type, timedelta
from typing import Any

import discord

from .constants import EMBED_COLOR, WIZARD_TIMEOUT_SECONDS
from .time_utils import (
    TimeInputError,
    combine_date_time,
    parse_timezone,
)
from .views import post_raid_panel

log = logging.getLogger(__name__)

MONTHS_NOMINATIVE = (
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
)
MONTHS_GENITIVE = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def _add_months(anchor: date, months: int) -> date:
    month_index = anchor.year * 12 + anchor.month - 1 + months
    year, month_index = divmod(month_index, 12)
    return date(year, month_index + 1, 1)


def _calendar_text(year: int, month: int) -> str:
    lines = [" ".join(WEEKDAYS)]
    for week in calendar.monthcalendar(year, month):
        lines.append(
            " ".join(f"{day:2d}" if day else "  " for day in week)
        )
    return "\n".join(lines)


class RaidDatePickerView(discord.ui.View):
    """Ephemeral month calendar used to choose the raid date."""

    def __init__(
        self,
        *,
        bot: Any,
        channel: discord.abc.Messageable,
        guild_id: int,
        created_by: int,
        raid_time: time_type,
        time_text: str,
        timezone_text: str,
        month_anchor: date | None = None,
    ) -> None:
        super().__init__(timeout=WIZARD_TIMEOUT_SECONDS)
        self.bot = bot
        self.channel = channel
        self.guild_id = int(guild_id)
        self.created_by = int(created_by)
        self.raid_time = raid_time
        self.time_text = time_text
        self.timezone_text = timezone_text
        _, self.timezone = parse_timezone(timezone_text)
        self.today = datetime.now(self.timezone).date()
        self.month_anchor = (
            month_anchor
            or date(self.today.year, self.today.month, 1)
        )
        self.message: discord.Message | None = None

        self._build_components()

    # ------------------------------------------------------------------ UI

    def _available_dates(self) -> list[date]:
        now = int(time.time())
        days_in_month = calendar.monthrange(
            self.month_anchor.year, self.month_anchor.month
        )[1]
        available: list[date] = []

        for day in range(1, days_in_month + 1):
            candidate = date(
                self.month_anchor.year, self.month_anchor.month, day
            )
            try:
                start_at = combine_date_time(
                    candidate, self.raid_time, self.timezone_text
                )
            except TimeInputError:
                continue
            if start_at > now:
                available.append(candidate)

        return available

    def _date_options(self, dates: list[date]) -> list[discord.SelectOption]:
        today = self.today
        tomorrow = today + timedelta(days=1)
        options: list[discord.SelectOption] = []

        for value in dates:
            if value == today:
                description = "Сегодня"
            elif value == tomorrow:
                description = "Завтра"
            else:
                description = None

            label = (
                f"{WEEKDAYS[value.weekday()]}, "
                f"{value.day:02d} {MONTHS_GENITIVE[value.month - 1]}"
            )
            options.append(
                discord.SelectOption(
                    label=label,
                    value=value.isoformat(),
                    description=description,
                )
            )

        return options

    def _build_components(self) -> None:
        self.clear_items()
        available = self._available_dates()
        first_half = [value for value in available if value.day <= 15]
        second_half = [value for value in available if value.day > 15]

        if first_half:
            select = discord.ui.Select(
                placeholder="Даты 1–15",
                options=self._date_options(first_half),
                min_values=1,
                max_values=1,
                row=0,
            )
            select.callback = self._on_date  # type: ignore[method-assign]
            self.add_item(select)

        if second_half:
            select = discord.ui.Select(
                placeholder="Даты 16–31",
                options=self._date_options(second_half),
                min_values=1,
                max_values=1,
                row=1,
            )
            select.callback = self._on_date  # type: ignore[method-assign]
            self.add_item(select)

        current_month = date(self.today.year, self.today.month, 1)
        prev_button = discord.ui.Button(
            label="◀",
            style=discord.ButtonStyle.secondary,
            row=2,
            disabled=self.month_anchor <= current_month,
        )
        prev_button.callback = functools.partial(self._navigate, months=-1)  # type: ignore[method-assign]
        self.add_item(prev_button)

        next_button = discord.ui.Button(
            label="▶",
            style=discord.ButtonStyle.secondary,
            row=2,
        )
        next_button.callback = functools.partial(self._navigate, months=1)  # type: ignore[method-assign]
        self.add_item(next_button)

        cancel_button = discord.ui.Button(
            label="Отмена",
            style=discord.ButtonStyle.secondary,
            row=2,
        )
        cancel_button.callback = self._cancel  # type: ignore[method-assign]
        self.add_item(cancel_button)

    def build_embed(self) -> discord.Embed:
        month_name = MONTHS_NOMINATIVE[self.month_anchor.month - 1]
        embed = discord.Embed(
            title="Календарь рейда",
            description=(
                f"**{month_name} {self.month_anchor.year}**\n"
                f"```\n{_calendar_text(self.month_anchor.year, self.month_anchor.month)}\n```\n"
                f"**Время:** {self.time_text} ({self.timezone_text})\n"
                "Выберите дату в меню ниже."
            ),
            color=EMBED_COLOR,
        )
        embed.set_footer(
            text=f"Доступны только будущие даты • {month_name} {self.month_anchor.year}"
        )
        return embed

    async def on_timeout(self) -> None:
        if self.message is None:
            return
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
            pass

    async def _navigate(
        self, interaction: discord.Interaction, *, months: int
    ) -> None:
        new_anchor = _add_months(self.month_anchor, months)
        current_month = date(self.today.year, self.today.month, 1)
        if new_anchor < current_month:
            await interaction.response.defer()
            return

        new_view = RaidDatePickerView(
            bot=self.bot,
            channel=self.channel,
            guild_id=self.guild_id,
            created_by=self.created_by,
            raid_time=self.raid_time,
            time_text=self.time_text,
            timezone_text=self.timezone_text,
            month_anchor=new_anchor,
        )
        self.stop()
        new_view.message = self.message
        await interaction.response.edit_message(
            embed=new_view.build_embed(), view=new_view
        )

    async def _cancel(self, interaction: discord.Interaction) -> None:
        self.stop()
        embed = discord.Embed(
            title="Создание рейда отменено",
            description="Календарь закрыт. Запустите `/создать` заново.",
            color=discord.Color.dark_grey(),
        )
        await interaction.response.edit_message(embed=embed, view=None)

    async def _on_date(self, interaction: discord.Interaction) -> None:
        assert isinstance(interaction.data, dict)
        values = interaction.data.get("values") or []
        if not values:
            return

        try:
            selected_date = date.fromisoformat(str(values[0]))
            start_at = combine_date_time(
                selected_date, self.raid_time, self.timezone_text
            )
        except (ValueError, TimeInputError):
            await interaction.response.send_message(
                "Не удалось выбрать эту дату. Попробуйте другую.",
                ephemeral=True,
            )
            return

        if start_at <= int(time.time()):
            await interaction.response.send_message(
                "Это время уже прошло. Выберите другую дату.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        settings = self.bot.store.settings_for(self.guild_id)
        raid = self.bot.store.create_raid(
            guild_id=self.guild_id,
            channel_id=self.channel.id,
            created_by=self.created_by,
            title=settings["title"],
            description="",
            start_at=start_at,
            limits=settings["limits"],
            role_emojis=settings["role_emojis"],
        )

        try:
            panel_message = await post_raid_panel(
                self.bot, self.channel, raid
            )
        except (discord.HTTPException, ValueError, TypeError):
            self.bot.store.delete_raid(raid["id"])
            log.exception("Не удалось опубликовать рейд после выбора даты")
            error = discord.Embed(
                title="Не удалось создать рейд",
                description=(
                    "Проверьте права бота на просмотр канала, отправку "
                    "сообщений и встраивание ссылок."
                ),
                color=discord.Color.red(),
            )
            await interaction.edit_original_response(embed=error, view=self)
            return

        self.bot.store.set_raid_message(
            raid["id"],
            channel_id=self.channel.id,
            message_id=panel_message.id,
        )
        self.stop()

        success = discord.Embed(
            title="Рейд создан",
            description=(
                f"{panel_message.jump_url}\n"
                f"Начало: <t:{start_at}:F> (<t:{start_at}:R>)"
            ),
            color=discord.Color.green(),
        )
        await interaction.edit_original_response(embed=success, view=None)
