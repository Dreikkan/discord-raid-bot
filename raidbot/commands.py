from __future__ import annotations

import json
import logging
import time
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from .assets import sync_role_icons, sync_spec_icons
from .constants import (
    MAX_DESCRIPTION_LENGTH,
    MAX_SPEC_NAME_LENGTH,
    MAX_TITLE_LENGTH,
    ROLE_LABELS,
    ROLE_ORDER,
)
from .embeds import build_settings_embed
from .specs import SpecImportError, normalize_emoji, normalize_role, parse_specs_payload
from .time_utils import TimeInputError, parse_start_at, parse_timezone
from .views import post_raid_panel

log = logging.getLogger(__name__)

ROLE_CHOICES = [
    app_commands.Choice(name="Танк", value="tank"),
    app_commands.Choice(name="Хил", value="heal"),
    app_commands.Choice(name="ДД", value="dd"),
]


def admin_only(func: Any) -> Any:
    return app_commands.checks.has_permissions(manage_guild=True)(func)


class RaidCog(commands.Cog):
    raid = app_commands.Group(
        name="рейд",
        description="Создание и управление рейдами",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )
    embed = app_commands.Group(
        name="эмбед",
        description="Сохранённые настройки эмбеда рейда",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )
    spec = app_commands.Group(
        name="специализация",
        description="Список специализаций и их иконок",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    def __init__(self, bot: Any) -> None:
        self.bot = bot

    # --------------------------------------------------------------- /рейд

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
            await interaction.followup.send(
                "Сначала добавьте хотя бы одну специализацию для ролей: "
                f"**{', '.join(missing_roles)}**.\n"
                "Используйте `/специализация добавить` или `/специализация импорт`.",
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

        icon_warning = ""
        role_icon_sync = await sync_role_icons(interaction.guild, self.bot.store)
        spec_icon_sync = await sync_spec_icons(interaction.guild, self.bot.store)
        if role_icon_sync.updated or spec_icon_sync.updated:
            settings = self.bot.store.settings_for(interaction.guild.id)

        icon_errors = [
            error
            for error in (role_icon_sync.error, spec_icon_sync.error)
            if error
        ]
        if icon_errors:
            details = "; ".join(icon_errors)
            if len(details) > 1000:
                details = f"{details[:999]}…"
            icon_warning = (
                "\n⚠️ Часть иконок не удалось применить: "
                + details
                + ". Выдайте боту право «Управлять выражениями» "
                "и выполните `/эмбед загрузить-иконки` "
                "и `/специализация загрузить-иконки`."
            )

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
            f"{warning}{icon_warning}",
            ephemeral=True,
        )

    # -------------------------------------------------------------- /эмбед

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

    @embed.command(name="иконки", description="Сохранить иконки ролей для эмбеда")
    @app_commands.rename(tank="танк", heal="хил", dd="дд")
    @app_commands.describe(
        tank="Emoji или кастомный emoji для заголовка «Танк»",
        heal="Emoji или кастомный emoji для заголовка «Хил»",
        dd="Emoji или кастомный emoji для заголовка «ДД»",
    )
    @admin_only
    async def set_role_icons(
        self,
        interaction: discord.Interaction,
        tank: str | None = None,
        heal: str | None = None,
        dd: str | None = None,
    ) -> None:
        updates = {
            "tank": tank,
            "heal": heal,
            "dd": dd,
        }
        if all(value is None for value in updates.values()):
            await interaction.response.send_message(
                "Укажите хотя бы одну иконку.", ephemeral=True
            )
            return

        saved: list[str] = []
        validated: dict[str, str] = {}
        try:
            for role, value in updates.items():
                if value is None:
                    continue
                emoji = normalize_emoji(value, required=True)
                validated[role] = emoji
        except SpecImportError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return

        for role, emoji in validated.items():
            saved.append(f"{ROLE_LABELS[role]}: {emoji}")
        self.bot.store.set_role_emojis(
            interaction.guild_id, validated, source="manual"
        )

        await interaction.response.send_message(
            "✅ Иконки сохранены:\n" + "\n".join(saved) + "\n"
            "Они будут использоваться в новых эмбедах.\n"
            "Автозагрузка из `assets` отключена; вернуть её можно командой "
            "`/эмбед загрузить-иконки`.",
            ephemeral=True,
        )

    @embed.command(
        name="загрузить-иконки",
        description="Загрузить иконки ролей из assets и применить их",
    )
    @admin_only
    async def upload_role_icons(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)

        if interaction.guild is None:
            await interaction.followup.send(
                "Команду нужно использовать на сервере.", ephemeral=True
            )
            return

        result = await sync_role_icons(
            interaction.guild, self.bot.store, force=True
        )
        if result.error:
            await interaction.followup.send(
                "⚠️ Иконки применены не полностью.\n"
                f"Ошибка: {result.error}.\n"
                "Проверьте право бота «Управлять выражениями» и свободные слоты emoji.",
                ephemeral=True,
            )
            return

        if result.uploaded:
            text = f"✅ Загружено новых emoji: **{result.uploaded}**."
        else:
            text = "✅ Иконки ролей уже были загружены и применены."
        await interaction.followup.send(
            f"{text}\nОни будут использоваться в новых эмбедах.",
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

    @embed.command(name="показать", description="Показать сохранённые настройки эмбеда")
    @admin_only
    async def show(self, interaction: discord.Interaction) -> None:
        settings = self.bot.store.settings_for(interaction.guild_id)
        counts = {
            role: sum(1 for spec in settings["specs"] if spec["role"] == role)
            for role in ROLE_ORDER
        }
        await interaction.response.send_message(
            embed=build_settings_embed(settings, counts), ephemeral=True
        )

    # -------------------------------------------------------- /специализация

    @spec.command(
        name="добавить",
        description="Добавить специализацию и её иконку",
    )
    @app_commands.rename(role="роль", name="название", icon="иконка")
    @app_commands.describe(
        role="Роль специализации",
        name="Название, например «Страж»",
        icon="Emoji или кастомный emoji из этого сервера",
    )
    @app_commands.choices(role=ROLE_CHOICES)
    @admin_only
    async def spec_add(
        self,
        interaction: discord.Interaction,
        role: str,
        name: str,
        icon: str,
    ) -> None:
        normalized_role = normalize_role(role)
        if normalized_role is None:
            await interaction.response.send_message(
                "Неизвестная роль.", ephemeral=True
            )
            return

        name = name.strip()
        if not name:
            await interaction.response.send_message(
                "Название специализации не может быть пустым.", ephemeral=True
            )
            return
        if len(name) > MAX_SPEC_NAME_LENGTH:
            await interaction.response.send_message(
                f"Название слишком длинное: максимум {MAX_SPEC_NAME_LENGTH} символов.",
                ephemeral=True,
            )
            return

        try:
            emoji = normalize_emoji(icon, required=True)
        except SpecImportError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return

        try:
            spec, created = self.bot.store.add_spec(
                interaction.guild_id, normalized_role, name, emoji
            )
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return

        action = "добавлена" if created else "обновлена"
        await interaction.response.send_message(
            f"✅ Специализация **{emoji} {spec['name']}** {action} "
            f"для роли «{ROLE_LABELS[normalized_role]}».",
            ephemeral=True,
        )

    @spec.command(
        name="загрузить-иконки",
        description="Загрузить иконки специализаций из assets и применить их",
    )
    @admin_only
    async def upload_spec_icons(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)

        if interaction.guild is None:
            await interaction.followup.send(
                "Команду нужно использовать на сервере.", ephemeral=True
            )
            return

        result = await sync_spec_icons(
            interaction.guild, self.bot.store, force=True
        )
        if result.error:
            await interaction.followup.send(
                "⚠️ Иконки специализаций применены не полностью.\n"
                f"Ошибка: {result.error}.\n"
                "Проверьте право бота «Управлять выражениями» и свободные слоты emoji.",
                ephemeral=True,
            )
            return

        if result.uploaded:
            text = f"✅ Загружено новых emoji: **{result.uploaded}**."
        else:
            text = "✅ Иконки специализаций уже были загружены и применены."
        await interaction.followup.send(
            f"{text}\nОни будут использоваться в новых эмбедах.",
            ephemeral=True,
        )

    @spec.command(name="удалить", description="Удалить специализацию")
    @app_commands.rename(spec="специализация")
    @app_commands.describe(spec="Начните вводить название специализации")
    @admin_only
    async def spec_remove(
        self, interaction: discord.Interaction, spec: str
    ) -> None:
        removed = self.bot.store.remove_spec(interaction.guild_id, spec)
        if removed is None:
            await interaction.response.send_message(
                "Специализация не найдена.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"✅ Специализация **{removed.get('emoji', '')} "
            f"{removed['name']}** удалена.",
            ephemeral=True,
        )

    @spec_remove.autocomplete("spec")
    async def spec_remove_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        if interaction.guild is None:
            return []

        query = current.strip().casefold()
        specs = self.bot.store.settings_for(interaction.guild_id)["specs"]
        choices = []
        for spec in specs:
            if query and query not in spec["name"].casefold():
                continue
            label = f"{ROLE_LABELS[spec['role']]} · {spec['name']}"[:100]
            choices.append(app_commands.Choice(name=label, value=spec["id"]))
            if len(choices) >= 25:
                break
        return choices

    @spec.command(name="список", description="Показать все специализации")
    @admin_only
    async def spec_list(self, interaction: discord.Interaction) -> None:
        settings = self.bot.store.settings_for(interaction.guild_id)
        specs = settings["specs"]
        if not specs:
            await interaction.response.send_message(
                "Список специализаций пуст. Добавьте их командой "
                "`/специализация добавить` или импортируйте JSON.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="Специализации",
            color=discord.Color.blurple(),
            description=(
                "Иконки кастомных emoji должны принадлежать этому серверу. "
                "Максимум — 25 специализаций на роль."
            ),
        )
        for role in ROLE_ORDER:
            role_specs = [spec for spec in specs if spec["role"] == role]
            value = "\n".join(
                f"{spec.get('emoji', '')} {spec['name']}".strip()
                for spec in role_specs
            )
            if not value:
                value = "—"
            if len(value) > 1024:
                value = f"{value[:1023]}…"
            embed.add_field(
                name=f"{ROLE_LABELS[role]} ({len(role_specs)})",
                value=value,
                inline=True,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @spec.command(
        name="импорт",
        description="Импортировать специализации из JSON-файла",
    )
    @app_commands.rename(file="файл", replace="заменить")
    @app_commands.describe(
        file="JSON-файл со списком специализаций",
        replace="Удалить старый список и заменить его новым",
    )
    @admin_only
    async def spec_import(
        self,
        interaction: discord.Interaction,
        file: discord.Attachment,
        replace: bool = False,
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)

        if file.size > 1_000_000:
            await interaction.followup.send(
                "Файл слишком большой. Максимум — 1 МБ.", ephemeral=True
            )
            return
        if not file.filename.lower().endswith(".json"):
            await interaction.followup.send(
                "Нужен файл с расширением .json.", ephemeral=True
            )
            return

        try:
            raw = await file.read()
            payload = json.loads(raw.decode("utf-8-sig"))
            imported = parse_specs_payload(payload)
            counts = self.bot.store.import_specs(
                interaction.guild_id, imported, replace=replace
            )
        except (UnicodeDecodeError, json.JSONDecodeError):
            await interaction.followup.send(
                "❌ Не удалось прочитать JSON. Проверьте кодировку UTF-8 и синтаксис.",
                ephemeral=True,
            )
            return
        except SpecImportError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return
        except ValueError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return

        counts_text = " · ".join(
            f"{ROLE_LABELS[role]}: {counts[role]}" for role in ROLE_ORDER
        )
        suffix = "Список заменён." if replace else "Список объединён с текущим."
        await interaction.followup.send(
            f"✅ Импорт завершён. {suffix}\n{counts_text}",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RaidCog(bot))
