from __future__ import annotations

import logging
import time
from typing import Any

import discord

from .activities import (
    ActivityError,
    format_schedules,
    next_activity_occurrence,
    parse_schedules,
)
from .gacha_roles import role_rewards
from .constants import (
    MAX_REMINDER_DELETE_MINUTES,
    MAX_REMINDER_DESCRIPTION_LENGTH,
    MAX_TITLE_LENGTH,
    ROLE_LABELS,
    ROLE_ORDER,
)
from .time_utils import TimeInputError, parse_timezone

log = logging.getLogger(__name__)

PANEL_TIMEOUT = 15 * 60
PANEL_COLOR = 0x5865F2


def _find_activity(
    settings: dict[str, Any], activity_id: str
) -> dict[str, Any] | None:
    for activity in settings.get("activities", []):
        if activity["id"] == activity_id:
            return activity
    return None


def _truncate(value: str, limit: int) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return f"{value[: limit - 1].rstrip()}…"


def _activity_preview(activity: dict[str, Any], settings: dict[str, Any]) -> str:
    schedules = format_schedules(activity.get("schedules", [])) or "—"
    channel = (
        f"<#{activity['channel_id']}>" if activity.get("channel_id") else "не задан"
    )
    role = f"<@&{activity['role_id']}>" if activity.get("role_id") else "не задана"
    description = _truncate(str(activity.get("description") or ""), 160) or "—"
    active = bool(
        activity.get("schedules")
        and activity.get("channel_id")
        and activity.get("role_id")
    )
    status = "активно" if active else "не настроено"

    lines = [
        f"**Расписание:** {schedules}",
        f"**Канал:** {channel}",
        f"**Роль:** {role}",
        f"**Описание:** {description}",
        f"**Автоудаление:** через {activity.get('delete_after_minutes', 60)} мин.",
        f"**Статус:** {status}",
    ]

    if active:
        occurrence = next_activity_occurrence(
            activity,
            str(settings.get("timezone") or "UTC"),
            after_ts=int(time.time()),
        )
        if occurrence is not None:
            start_at, _ = occurrence
            lines.append(f"**Ближайшее начало:** <t:{start_at}:F>")

    return "\n".join(lines)


def build_settings_embed(settings: dict[str, Any]) -> discord.Embed:
    role_emojis = settings.get("role_emojis", {})
    limits = settings.get("limits", {})
    limit_parts = [
        f"{role_emojis.get(role, '')} {ROLE_LABELS[role]}: {limits.get(role, 0)}".strip()
        for role in ROLE_ORDER
    ]

    embed = discord.Embed(
        title="Настройки",
        description=(
            "Настройки рейда, напоминаний об активностях и пула гачи.\n"
            "Изменения сохраняются автоматически."
        ),
        color=PANEL_COLOR,
    )
    embed.add_field(
        name="Рейд",
        value=(
            f"**Название:** {settings.get('title') or '—'}\n"
            f"**Лимиты:** {' · '.join(limit_parts)}\n"
            f"**Часовой пояс:** {settings.get('timezone') or '—'}"
        ),
        inline=False,
    )

    gacha_items = settings.get("gacha_items", [])
    legendary_count = sum(
        1 for item in gacha_items if item.get("rarity") == "legendary"
    )
    embed.add_field(
        name="Гача",
        value=(
            f"**Предметов в пуле:** {len(gacha_items)}\n"
            f"**Легендарных:** {legendary_count}\n"
            "Пул, картинки и начисление валюты — кнопкой ниже."
        ),
        inline=False,
    )

    rewards = role_rewards()
    if rewards:
        embed.add_field(
            name="Гарантированные роли",
            value=(
                "\n".join(
                    f"**{reward['name']}** — {reward['milestone']} круток"
                    for reward in rewards
                )
                + "\nРоли выдаются автоматически при достижении порога."
            ),
            inline=False,
        )

    activities = settings.get("activities", [])
    for activity in activities:
        embed.add_field(
            name=str(activity["name"])[:256],
            value=_activity_preview(activity, settings),
            inline=False,
        )

    if not activities:
        embed.add_field(
            name="Активности",
            value="Активности ещё не созданы.",
            inline=False,
        )

    embed.set_footer(
        text=(
            "Выберите активность, откройте настройки рейда "
            "или настройки гачи."
        )
    )
    return embed


def build_activity_embed(
    activity: dict[str, Any], settings: dict[str, Any]
) -> discord.Embed:
    schedules = format_schedules(activity.get("schedules", [])) or "—"
    channel = (
        f"<#{activity['channel_id']}>" if activity.get("channel_id") else "не задан"
    )
    role = f"<@&{activity['role_id']}>" if activity.get("role_id") else "не задана"
    description = str(activity.get("description") or "").strip()
    active = bool(
        activity.get("schedules")
        and activity.get("channel_id")
        and activity.get("role_id")
    )

    embed = discord.Embed(
        title=str(activity["name"]),
        description=description or "*Описание не задано.*",
        color=PANEL_COLOR,
    )
    embed.add_field(name="Расписание", value=schedules, inline=False)
    embed.add_field(name="Канал", value=channel, inline=True)
    embed.add_field(name="Роль", value=role, inline=True)
    embed.add_field(
        name="Автоудаление",
        value=f"через {activity.get('delete_after_minutes', 60)} мин.",
        inline=True,
    )
    embed.add_field(
        name="Статус",
        value=(
            "Активно"
            if active
            else "Не настроено: укажите канал и роль"
        ),
        inline=True,
    )

    if active:
        occurrence = next_activity_occurrence(
            activity,
            str(settings.get("timezone") or "UTC"),
            after_ts=int(time.time()),
        )
        if occurrence is not None:
            start_at, _ = occurrence
            embed.add_field(
                name="Ближайшее напоминание",
                value=f"<t:{start_at - 15 * 60}:F> · <t:{start_at - 15 * 60}:R>",
                inline=False,
            )

    return embed


class PanelView(discord.ui.View):
    def __init__(self, bot: Any, guild_id: int) -> None:
        super().__init__(timeout=PANEL_TIMEOUT)
        self.bot = bot
        self.guild_id = int(guild_id)
        self.message: discord.Message | None = None

    def settings(self) -> dict[str, Any]:
        return self.bot.store.settings_for(self.guild_id)

    def build_embed(self) -> discord.Embed:
        raise NotImplementedError

    def build_files(self) -> list[discord.File]:
        return []

    async def on_timeout(self) -> None:
        if self.message is None:
            return
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
            pass

    async def show_view(
        self, interaction: discord.Interaction, new_view: "PanelView"
    ) -> None:
        self.stop()
        embed = new_view.build_embed()
        files = new_view.build_files()

        if interaction.message is not None:
            new_view.message = interaction.message
            await interaction.response.edit_message(
                embed=embed, view=new_view, attachments=files
            )
            return

        if files:
            await interaction.response.send_message(
                embed=embed, view=new_view, files=files, ephemeral=True
            )
        else:
            await interaction.response.send_message(
                embed=embed, view=new_view, ephemeral=True
            )
        new_view.message = await interaction.original_response()


class SettingsView(PanelView):
    def __init__(self, bot: Any, guild_id: int) -> None:
        super().__init__(bot, guild_id)
        activities = self.settings().get("activities", [])
        button_row = 1 if activities else 0

        if activities:
            options = [
                discord.SelectOption(
                    label=str(activity["name"])[:100],
                    value=str(activity["id"]),
                    description=(
                        "Активно"
                        if activity.get("channel_id") and activity.get("role_id")
                        else "Не настроено"
                    ),
                )
                for activity in activities[:25]
            ]
            select = discord.ui.Select(
                placeholder="Выберите активность для настройки",
                options=options,
                min_values=1,
                max_values=1,
                row=0,
            )
            select.callback = self._open_activity  # type: ignore[method-assign]
            self.add_item(select)

        raid_button = discord.ui.Button(
            label="Настройки рейда",
            emoji="⚙️",
            style=discord.ButtonStyle.primary,
            row=button_row,
        )
        raid_button.callback = self._open_raid  # type: ignore[method-assign]
        self.add_item(raid_button)

        add_button = discord.ui.Button(
            label="Добавить активность",
            emoji="➕",
            style=discord.ButtonStyle.secondary,
            row=button_row,
        )
        add_button.callback = self._open_add_activity  # type: ignore[method-assign]
        self.add_item(add_button)

        gacha_button = discord.ui.Button(
            label="Настройки гачи",
            emoji="🎁",
            style=discord.ButtonStyle.secondary,
            row=button_row,
        )
        gacha_button.callback = self._open_gacha_pool  # type: ignore[method-assign]
        self.add_item(gacha_button)

    def build_embed(self) -> discord.Embed:
        return build_settings_embed(self.settings())

    async def _open_activity(self, interaction: discord.Interaction) -> None:
        assert isinstance(interaction.data, dict)
        values = interaction.data.get("values") or []
        if not values:
            return

        settings = self.settings()
        activity = _find_activity(settings, str(values[0]))
        if activity is None:
            await interaction.response.send_message(
                "Активность не найдена.", ephemeral=True
            )
            return

        new_view = ActivitySettingsView(
            self.bot, self.guild_id, str(activity["id"])
        )
        await self.show_view(interaction, new_view)

    async def _open_raid(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            GeneralSettingsModal(self.bot, self.guild_id, self)
        )

    async def _open_add_activity(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            AddActivityModal(self.bot, self.guild_id, self)
        )

    async def _open_gacha_pool(self, interaction: discord.Interaction) -> None:
        from .gacha_settings import GachaPoolView

        await self.show_view(
            interaction, GachaPoolView(self.bot, self.guild_id)
        )


class ActivitySettingsView(PanelView):
    def __init__(self, bot: Any, guild_id: int, activity_id: str) -> None:
        super().__init__(bot, guild_id)
        self.activity_id = str(activity_id)

        for label, callback in (
            ("Описание", self._open_description),
            ("Расписание", self._open_schedule),
            ("Канал", self._open_channel),
            ("Роль", self._open_role),
            ("Автоудаление", self._open_delete_after),
        ):
            button = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.secondary,
                row=0,
            )
            button.callback = callback
            self.add_item(button)

        back = discord.ui.Button(
            label="Назад",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        back.callback = self._back  # type: ignore[method-assign]
        self.add_item(back)

    def activity(self) -> dict[str, Any] | None:
        return _find_activity(self.settings(), self.activity_id)

    def build_embed(self) -> discord.Embed:
        activity = self.activity()
        if activity is None:
            return discord.Embed(
                title="Активность не найдена",
                color=discord.Color.red(),
            )
        return build_activity_embed(activity, self.settings())

    async def _back(self, interaction: discord.Interaction) -> None:
        new_view = SettingsView(self.bot, self.guild_id)
        await self.show_view(interaction, new_view)

    async def _open_description(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            ActivityDescriptionModal(
                self.bot, self.guild_id, self.activity_id, self
            )
        )

    async def _open_schedule(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            ActivityScheduleModal(
                self.bot, self.guild_id, self.activity_id, self
            )
        )

    async def _open_delete_after(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            ActivityDeleteAfterModal(
                self.bot, self.guild_id, self.activity_id, self
            )
        )

    async def _open_channel(self, interaction: discord.Interaction) -> None:
        new_view = ActivityChannelView(
            self.bot, self.guild_id, self.activity_id
        )
        await self.show_view(interaction, new_view)

    async def _open_role(self, interaction: discord.Interaction) -> None:
        new_view = ActivityRoleView(self.bot, self.guild_id, self.activity_id)
        await self.show_view(interaction, new_view)


class ActivityChannelView(PanelView):
    def __init__(self, bot: Any, guild_id: int, activity_id: str) -> None:
        super().__init__(bot, guild_id)
        self.activity_id = str(activity_id)

        select = discord.ui.ChannelSelect(
            placeholder="Выберите канал",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=0,
        )
        select.callback = self._on_channel  # type: ignore[method-assign]
        self.add_item(select)

        back = discord.ui.Button(
            label="Назад", style=discord.ButtonStyle.secondary, row=1
        )
        back.callback = self._back  # type: ignore[method-assign]
        self.add_item(back)

    def build_embed(self) -> discord.Embed:
        activity = _find_activity(self.settings(), self.activity_id)
        name = activity["name"] if activity else "Активность"
        activity_value = (
            f"<#{activity['channel_id']}>"
            if activity and activity.get("channel_id")
            else "не задан"
        )
        return discord.Embed(
            title=f"Канал: {name}",
            description=f"**Текущий канал:** {activity_value}\nВыберите канал.",
            color=PANEL_COLOR,
        )

    async def _on_channel(self, interaction: discord.Interaction) -> None:
        assert isinstance(interaction.data, dict)
        values = interaction.data.get("values") or []
        if not values:
            return

        guild = self.bot.get_guild(self.guild_id)
        if guild is None:
            await interaction.response.send_message(
                "Сервер не найден.", ephemeral=True
            )
            return
        channel = guild.get_channel(int(values[0]))
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Выберите текстовый канал.", ephemeral=True
            )
            return
        if guild.me is not None:
            permissions = channel.permissions_for(guild.me)
            if not permissions.send_messages:
                await interaction.response.send_message(
                    "У бота нет прав на отправку сообщений в выбранный канал.",
                    ephemeral=True,
                )
                return

        activity = _find_activity(self.settings(), self.activity_id)
        if activity is None:
            await interaction.response.send_message(
                "Активность не найдена.", ephemeral=True
            )
            return

        activity["channel_id"] = channel.id
        try:
            self.bot.store.save_activity(self.guild_id, activity)
        except ActivityError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return

        new_view = ActivitySettingsView(
            self.bot, self.guild_id, self.activity_id
        )
        await self.show_view(interaction, new_view)

    async def _back(self, interaction: discord.Interaction) -> None:
        new_view = ActivitySettingsView(
            self.bot, self.guild_id, self.activity_id
        )
        await self.show_view(interaction, new_view)


class ActivityRoleView(PanelView):
    def __init__(self, bot: Any, guild_id: int, activity_id: str) -> None:
        super().__init__(bot, guild_id)
        self.activity_id = str(activity_id)

        select = discord.ui.RoleSelect(
            placeholder="Выберите роль",
            min_values=1,
            max_values=1,
            row=0,
        )
        select.callback = self._on_role  # type: ignore[method-assign]
        self.add_item(select)

        back = discord.ui.Button(
            label="Назад", style=discord.ButtonStyle.secondary, row=1
        )
        back.callback = self._back  # type: ignore[method-assign]
        self.add_item(back)

    def build_embed(self) -> discord.Embed:
        activity = _find_activity(self.settings(), self.activity_id)
        name = activity["name"] if activity else "Активность"
        role_value = (
            f"<@&{activity['role_id']}>"
            if activity and activity.get("role_id")
            else "не задана"
        )
        return discord.Embed(
            title=f"Роль: {name}",
            description=f"**Текущая роль:** {role_value}\nВыберите роль.",
            color=PANEL_COLOR,
        )

    async def _on_role(self, interaction: discord.Interaction) -> None:
        assert isinstance(interaction.data, dict)
        values = interaction.data.get("values") or []
        if not values:
            return

        guild = self.bot.get_guild(self.guild_id)
        if guild is None:
            await interaction.response.send_message(
                "Сервер не найден.", ephemeral=True
            )
            return
        role = guild.get_role(int(values[0]))
        if role is None:
            await interaction.response.send_message(
                "Роль не найдена.", ephemeral=True
            )
            return

        activity = _find_activity(self.settings(), self.activity_id)
        if activity is None:
            await interaction.response.send_message(
                "Активность не найдена.", ephemeral=True
            )
            return

        activity["role_id"] = role.id
        try:
            self.bot.store.save_activity(self.guild_id, activity)
        except ActivityError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return

        new_view = ActivitySettingsView(
            self.bot, self.guild_id, self.activity_id
        )
        await self.show_view(interaction, new_view)

    async def _back(self, interaction: discord.Interaction) -> None:
        new_view = ActivitySettingsView(
            self.bot, self.guild_id, self.activity_id
        )
        await self.show_view(interaction, new_view)


class GeneralSettingsModal(discord.ui.Modal):
    def __init__(self, bot: Any, guild_id: int, parent: SettingsView) -> None:
        super().__init__(title="Настройки рейда")
        self.bot = bot
        self.guild_id = int(guild_id)
        self.parent_view = parent
        settings = bot.store.settings_for(guild_id)

        self.title_input = discord.ui.TextInput(
            label="Название рейда",
            default=str(settings.get("title") or ""),
            max_length=MAX_TITLE_LENGTH,
            required=True,
        )
        self.tank_input = discord.ui.TextInput(
            label="Танки",
            default=str(settings["limits"]["tank"]),
            max_length=2,
            required=True,
        )
        self.heal_input = discord.ui.TextInput(
            label="Хилы",
            default=str(settings["limits"]["heal"]),
            max_length=2,
            required=True,
        )
        self.dd_input = discord.ui.TextInput(
            label="ДД",
            default=str(settings["limits"]["dd"]),
            max_length=2,
            required=True,
        )
        self.timezone_input = discord.ui.TextInput(
            label="Часовой пояс",
            default=str(settings.get("timezone") or ""),
            max_length=64,
            required=True,
        )

        for item in (
            self.title_input,
            self.tank_input,
            self.heal_input,
            self.dd_input,
            self.timezone_input,
        ):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        title = self.title_input.value.strip()
        if not title or "\n" in title or "\r" in title:
            await interaction.response.send_message(
                "❌ Название должно быть непустой одной строкой.",
                ephemeral=True,
            )
            return

        try:
            limits = {
                "tank": int(self.tank_input.value),
                "heal": int(self.heal_input.value),
                "dd": int(self.dd_input.value),
            }
        except ValueError:
            await interaction.response.send_message(
                "❌ Лимиты должны быть целыми числами.", ephemeral=True
            )
            return

        if any(not 1 <= value <= 50 for value in limits.values()):
            await interaction.response.send_message(
                "❌ Лимиты должны быть от 1 до 50.", ephemeral=True
            )
            return

        try:
            canonical_timezone, _ = parse_timezone(self.timezone_input.value)
        except TimeInputError as exc:
            await interaction.response.send_message(
                f"❌ {exc}", ephemeral=True
            )
            return

        self.bot.store.set_title(self.guild_id, title)
        self.bot.store.set_limits(self.guild_id, limits)
        self.bot.store.set_timezone(self.guild_id, canonical_timezone)

        new_view = SettingsView(self.bot, self.guild_id)
        await self.parent_view.show_view(interaction, new_view)


class AddActivityModal(discord.ui.Modal):
    def __init__(self, bot: Any, guild_id: int, parent: SettingsView) -> None:
        super().__init__(title="Новая активность")
        self.bot = bot
        self.guild_id = int(guild_id)
        self.parent_view = parent

        self.name_input = discord.ui.TextInput(
            label="Название",
            max_length=100,
            required=True,
        )
        self.schedule_input = discord.ui.TextInput(
            label="Расписание",
            placeholder="Вторник 20:00-22:00; Суббота 19:00-21:00",
            style=discord.TextStyle.paragraph,
            max_length=1000,
            required=True,
        )
        self.description_input = discord.ui.TextInput(
            label="Описание",
            style=discord.TextStyle.paragraph,
            max_length=MAX_REMINDER_DESCRIPTION_LENGTH,
            required=False,
        )
        for item in (
            self.name_input,
            self.schedule_input,
            self.description_input,
        ):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            schedules = parse_schedules(self.schedule_input.value)
        except ActivityError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return

        activity = {
            "name": self.name_input.value.strip(),
            "description": self.description_input.value.strip(),
            "channel_id": None,
            "role_id": None,
            "delete_after_minutes": 60,
            "schedules": schedules,
            "last_sent_event_at": 0,
        }
        try:
            saved = self.bot.store.save_activity(self.guild_id, activity)
        except ActivityError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return

        new_view = ActivitySettingsView(
            self.bot, self.guild_id, saved["id"]
        )
        await self.parent_view.show_view(interaction, new_view)


class ActivityDescriptionModal(discord.ui.Modal):
    def __init__(
        self,
        bot: Any,
        guild_id: int,
        activity_id: str,
        parent: ActivitySettingsView,
    ) -> None:
        super().__init__(title="Описание активности")
        self.bot = bot
        self.guild_id = int(guild_id)
        self.activity_id = activity_id
        self.parent_view = parent
        settings = bot.store.settings_for(guild_id)
        activity = _find_activity(settings, activity_id)
        current = str(activity.get("description", "")) if activity else ""

        self.description_input = discord.ui.TextInput(
            label="Описание",
            style=discord.TextStyle.paragraph,
            default=current,
            max_length=MAX_REMINDER_DESCRIPTION_LENGTH,
            required=False,
        )
        self.add_item(self.description_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        activity = _find_activity(
            self.bot.store.settings_for(self.guild_id), self.activity_id
        )
        if activity is None:
            await interaction.response.send_message(
                "Активность не найдена.", ephemeral=True
            )
            return

        activity["description"] = self.description_input.value.strip()
        try:
            self.bot.store.save_activity(self.guild_id, activity)
        except ActivityError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return

        new_view = ActivitySettingsView(
            self.bot, self.guild_id, self.activity_id
        )
        await self.parent_view.show_view(interaction, new_view)


class ActivityScheduleModal(discord.ui.Modal):
    def __init__(
        self,
        bot: Any,
        guild_id: int,
        activity_id: str,
        parent: ActivitySettingsView,
    ) -> None:
        super().__init__(title="Расписание активности")
        self.bot = bot
        self.guild_id = int(guild_id)
        self.activity_id = activity_id
        self.parent_view = parent
        settings = bot.store.settings_for(guild_id)
        activity = _find_activity(settings, activity_id)
        current = (
            format_schedules(activity.get("schedules", [])) if activity else ""
        )

        self.schedule_input = discord.ui.TextInput(
            label="Расписание",
            placeholder="Вторник 20:00-22:00; Суббота 19:00-21:00",
            style=discord.TextStyle.paragraph,
            default=current,
            max_length=1000,
            required=True,
        )
        self.add_item(self.schedule_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            schedules = parse_schedules(self.schedule_input.value)
        except ActivityError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return

        activity = _find_activity(
            self.bot.store.settings_for(self.guild_id), self.activity_id
        )
        if activity is None:
            await interaction.response.send_message(
                "Активность не найдена.", ephemeral=True
            )
            return

        activity["schedules"] = schedules
        activity["last_sent_event_at"] = 0
        try:
            self.bot.store.save_activity(self.guild_id, activity)
        except ActivityError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return

        new_view = ActivitySettingsView(
            self.bot, self.guild_id, self.activity_id
        )
        await self.parent_view.show_view(interaction, new_view)


class ActivityDeleteAfterModal(discord.ui.Modal):
    def __init__(
        self,
        bot: Any,
        guild_id: int,
        activity_id: str,
        parent: ActivitySettingsView,
    ) -> None:
        super().__init__(title="Автоудаление")
        self.bot = bot
        self.guild_id = int(guild_id)
        self.activity_id = activity_id
        self.parent_view = parent
        settings = bot.store.settings_for(guild_id)
        activity = _find_activity(settings, activity_id)
        current = str(activity.get("delete_after_minutes", 60)) if activity else "60"

        self.minutes_input = discord.ui.TextInput(
            label="Удалить через (минут)",
            default=current,
            max_length=5,
            required=True,
        )
        self.add_item(self.minutes_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            minutes = int(self.minutes_input.value)
        except ValueError:
            await interaction.response.send_message(
                "❌ Укажите целое число минут.", ephemeral=True
            )
            return
        if not 1 <= minutes <= MAX_REMINDER_DELETE_MINUTES:
            await interaction.response.send_message(
                "❌ Время автоудаления должно быть от 1 до "
                f"{MAX_REMINDER_DELETE_MINUTES} минут.",
                ephemeral=True,
            )
            return

        activity = _find_activity(
            self.bot.store.settings_for(self.guild_id), self.activity_id
        )
        if activity is None:
            await interaction.response.send_message(
                "Активность не найдена.", ephemeral=True
            )
            return

        activity["delete_after_minutes"] = minutes
        try:
            self.bot.store.save_activity(self.guild_id, activity)
        except ActivityError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return

        new_view = ActivitySettingsView(
            self.bot, self.guild_id, self.activity_id
        )
        await self.parent_view.show_view(interaction, new_view)
