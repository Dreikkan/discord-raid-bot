from __future__ import annotations

import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from .constants import ROLE_LABELS, ROLE_ORDER
from .date_picker import RaidDatePickerView
from .gacha_panel import GachaPanelView
from .settings_panel import SettingsView
from .time_utils import TimeInputError, parse_time_value

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
        name="настройки",
        description="Открыть настройки рейда и напоминаний об активностях",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    @admin_only
    async def settings(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Команду нужно использовать на сервере.", ephemeral=True
            )
            return

        view = SettingsView(self.bot, interaction.guild.id)
        await interaction.response.send_message(
            embed=view.build_embed(), view=view, ephemeral=True
        )
        view.message = await interaction.original_response()

    @app_commands.command(
        name="гача",
        description="Открыть гачу и получить коллекционную награду",
    )
    @app_commands.guild_only()
    async def gacha(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Команду нужно использовать на сервере.", ephemeral=True
            )
            return

        view = GachaPanelView(
            self.bot, interaction.guild.id, interaction.user.id
        )
        await interaction.response.send_message(
            embed=view.build_embed(), view=view, ephemeral=True
        )
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RaidCog(bot))
