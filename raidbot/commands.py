from __future__ import annotations

import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from .constants import MAX_TITLE_LENGTH, ROLE_LABELS, ROLE_ORDER
from .date_picker import RaidDatePickerView
from .time_utils import TimeInputError, parse_time_value, parse_timezone

log = logging.getLogger(__name__)


def admin_only(func: Any) -> Any:
    return app_commands.checks.has_permissions(manage_guild=True)(func)


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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RaidCog(bot))
