from __future__ import annotations

import logging
import time
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from .constants import (
    MAX_DESCRIPTION_LENGTH,
    MAX_TITLE_LENGTH,
    ROLE_LABELS,
    ROLE_ORDER,
)
from .time_utils import TimeInputError, parse_start_at, parse_timezone
from .views import post_raid_panel

log = logging.getLogger(__name__)


def admin_only(func: Any) -> Any:
    return app_commands.checks.has_permissions(manage_guild=True)(func)


class RaidCog(commands.Cog):
    raid = app_commands.Group(
        name="рейд",
        description="Создание рейдов",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )
    embed = app_commands.Group(
        name="эмбед",
        description="Сохранённые настройки эмбеда рейда",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    def __init__(self, bot: Any) -> None:
        self.bot = bot

    @raid.command(
        name="создать",
        description="Опубликовать новый эмбед рейда с кнопкой регистрации",
    )
    @app_commands.rename(
        description="описание", date_value="дата", time_value="время"
    )
    @app_commands.describe(
        description="Новое описание рейда. Оно не сохраняется для следующих рейдов.",
        date_value="Дата в формате ДД.ММ.ГГГГ, например 26.10.2026",
        time_value="Время в формате ЧЧ:ММ, например 20:30",
    )
    @admin_only
    async def create(
        self,
        interaction: discord.Interaction,
        description: str,
        date_value: str,
        time_value: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)

        if interaction.guild is None or interaction.channel is None:
            await interaction.followup.send(
                "Команду нужно использовать на сервере в текстовом канале.",
                ephemeral=True,
            )
            return

        description = description.strip()
        if not description:
            await interaction.followup.send(
                "Описание не может быть пустым.", ephemeral=True
            )
            return
        if len(description) > MAX_DESCRIPTION_LENGTH:
            await interaction.followup.send(
                f"Описание слишком длинное: максимум {MAX_DESCRIPTION_LENGTH} символов.",
                ephemeral=True,
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
            await interaction.followup.send(
                "❌ В каталоге специализаций отсутствуют роли: "
                f"**{', '.join(missing_roles)}**. Проверьте "
                "`config/specializations.json`.",
                ephemeral=True,
            )
            return

        try:
            start_at = parse_start_at(
                date_value, time_value, settings["timezone"]
            )
        except TimeInputError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return

        now = int(time.time())
        if start_at <= now:
            await interaction.followup.send(
                "❌ Указанные дата и время уже прошли. "
                f"Проверьте дату и часовой пояс **{settings['timezone']}**.",
                ephemeral=True,
            )
            return

        raid = self.bot.store.create_raid(
            guild_id=interaction.guild.id,
            channel_id=interaction.channel.id,
            created_by=interaction.user.id,
            title=settings["title"],
            description=description,
            start_at=start_at,
            limits=settings["limits"],
            role_emojis=settings["role_emojis"],
        )

        try:
            message = await post_raid_panel(self.bot, interaction.channel, raid)
        except (discord.HTTPException, ValueError, TypeError):
            self.bot.store.delete_raid(raid["id"])
            log.exception("Не удалось опубликовать эмбед рейда")
            await interaction.followup.send(
                "❌ Не удалось опубликовать эмбед. Проверьте права бота "
                "на просмотр канала, отправку сообщений и встраивание ссылок.",
                ephemeral=True,
            )
            return

        self.bot.store.set_raid_message(
            raid["id"],
            channel_id=interaction.channel.id,
            message_id=message.id,
        )

        warning = ""
        if start_at - now <= 15 * 60:
            warning = "\n⏰ До начала меньше 15 минут — напоминание уйдёт сразу."

        await interaction.followup.send(
            f"✅ Рейд создан: {message.jump_url}\n"
            f"Начало: <t:{start_at}:F>.\n"
            f"Дата и время указаны в часовом поясе **{settings['timezone']}**, "
            "участники увидят их в своём локальном времени."
            f"{warning}",
            ephemeral=True,
        )

    @embed.command(name="название", description="Сохранить название для новых эмбедов")
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

    @embed.command(name="лимиты", description="Сохранить количество мест по ролям")
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
            "Они применяются к новым эмбедам.",
            ephemeral=True,
        )

    @embed.command(
        name="часовой_пояс",
        description="Сохранить часовой пояс для ввода даты и времени",
    )
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
            "Администратор вводит дату и время в этом поясе, а каждый участник "
            "увидит их в своём локальном времени.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RaidCog(bot))
