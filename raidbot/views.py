from __future__ import annotations

import functools
import logging
import time
from typing import Any

import discord

from .constants import (
    ABSENT_EMOJI,
    BENCH_EMOJI,
    EMBED_COLOR,
    MAX_SPECS_PER_ROLE,
    PUBLIC_BUTTON_PREFIX,
    ROLE_LABELS,
    ROLE_ORDER,
    STATUS_ABSENT,
    STATUS_BENCH,
    STATUS_LABELS,
    STATUS_MAIN,
    WIZARD_TIMEOUT_SECONDS,
)
from .embeds import build_raid_embed
from .registration import count_main_for_role, resolve_requested_status
from .specs import to_partial_emoji

log = logging.getLogger(__name__)


def _is_open(raid: dict[str, Any]) -> bool:
    return int(raid.get("start_at", 0)) > int(time.time())


def _current_registration(
    raid: dict[str, Any], user_id: int | str
) -> dict[str, Any] | None:
    return raid.get("registrations", {}).get(str(user_id))


def _registration_description(registration: dict[str, Any]) -> str:
    emoji = str(registration.get("spec_emoji") or "").strip()
    spec_name = str(registration.get("spec_name") or "Специализация")
    role = ROLE_LABELS.get(str(registration.get("role")), "Роль")
    status = STATUS_LABELS.get(str(registration.get("status")), "Статус")
    details = f"{emoji} {spec_name}".strip()
    return f"{role} · {details} · {status}"


def _wizard_embed(
    raid: dict[str, Any], title: str, description: str
) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=EMBED_COLOR)
    embed.set_footer(text=f"Рейд: {raid.get('title', 'Рейд')}")
    return embed


class RaidPanelView(discord.ui.View):
    """Persistent view with the public registration button (page 1)."""

    def __init__(self, bot: Any, raid_id: str) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.raid_id = raid_id

        button = discord.ui.Button(
            label="Зарегистрироваться",
            emoji="✍️",
            style=discord.ButtonStyle.primary,
            custom_id=f"{PUBLIC_BUTTON_PREFIX}{raid_id}",
        )
        button.callback = self._start_registration  # type: ignore[method-assign]
        self.add_item(button)

    async def _start_registration(self, interaction: discord.Interaction) -> None:
        raid = self.bot.store.get_raid(self.raid_id)
        if raid is None:
            await interaction.response.send_message(
                "Этот рейд больше не существует.", ephemeral=True
            )
            return

        if not _is_open(raid):
            await interaction.response.send_message(
                "Запись на этот рейд уже закрыта.", ephemeral=True
            )
            return

        settings = self.bot.store.settings_for(raid["guild_id"])
        if not settings.get("specs"):
            await interaction.response.send_message(
                "Администратор ещё не добавил специализации. "
                "Регистрация временно недоступна.",
                ephemeral=True,
            )
            return

        view = RoleSelectView(self.bot, self.raid_id, interaction.user.id)
        await interaction.response.send_message(
            embed=view.build_embed(raid), view=view, ephemeral=True
        )
        view.message = await interaction.original_response()


class WizardView(discord.ui.View):
    def __init__(self, bot: Any, raid_id: str, user_id: int) -> None:
        super().__init__(timeout=WIZARD_TIMEOUT_SECONDS)
        self.bot = bot
        self.raid_id = raid_id
        self.user_id = int(user_id)
        self.message: discord.Message | None = None

    async def on_timeout(self) -> None:
        if self.message is None:
            return
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
            pass

    def _cancel_button(self) -> discord.ui.Button:
        button = discord.ui.Button(
            label="Отмена", style=discord.ButtonStyle.secondary
        )
        button.callback = self._cancel  # type: ignore[method-assign]
        return button

    async def _cancel(self, interaction: discord.Interaction) -> None:
        self.stop()
        embed = discord.Embed(
            title="Регистрация отменена",
            description="Вы можете начать заново кнопкой «Зарегистрироваться».",
            color=discord.Color.dark_grey(),
        )
        await interaction.response.edit_message(embed=embed, view=None)

    def _move_to(
        self, interaction: discord.Interaction, new_view: "WizardView", raid: dict[str, Any]
    ) -> Any:
        self.stop()
        new_view.message = self.message
        return interaction.response.edit_message(
            embed=new_view.build_embed(raid), view=new_view
        )

    def build_embed(self, raid: dict[str, Any]) -> discord.Embed:
        raise NotImplementedError


class RoleSelectView(WizardView):
    def __init__(
        self,
        bot: Any,
        raid_id: str,
        user_id: int,
        *,
        warning: str | None = None,
    ) -> None:
        super().__init__(bot, raid_id, user_id)
        self.warning = warning

        raid = bot.store.get_raid(raid_id) or {}
        current = _current_registration(raid, user_id) or {}
        current_role = current.get("role")

        options: list[discord.SelectOption] = []
        for role in ROLE_ORDER:
            emoji = raid.get("role_emojis", {}).get(role)
            options.append(
                discord.SelectOption(
                    label=ROLE_LABELS[role],
                    value=role,
                    emoji=to_partial_emoji(emoji) if emoji else None,
                    default=(role == current_role),
                )
            )

        select = discord.ui.Select(
            placeholder="Выберите роль",
            min_values=1,
            max_values=1,
            options=options,
        )
        select.callback = self._on_role  # type: ignore[method-assign]
        self.add_item(select)
        self.add_item(self._cancel_button())

    def build_embed(self, raid: dict[str, Any]) -> discord.Embed:
        lines = [
            "**Шаг 1 из 3 · Роль**",
            "Выберите, кем вы пойдёте в рейд.",
        ]

        if self.warning:
            lines.extend(("", f"⚠️ {self.warning}"))

        current = _current_registration(raid, self.user_id)
        if current:
            lines.extend(("", f"**Текущая запись:** {_registration_description(current)}"))

        return _wizard_embed(raid, "Регистрация на рейд", "\n".join(lines))

    async def _on_role(self, interaction: discord.Interaction) -> None:
        assert isinstance(interaction.data, dict)
        values = interaction.data.get("values") or []
        if not values:
            return

        role = str(values[0])
        if role not in ROLE_ORDER:
            await interaction.response.send_message(
                "Неизвестная роль. Попробуйте ещё раз.", ephemeral=True
            )
            return

        raid = self.bot.store.get_raid(self.raid_id)
        if raid is None:
            self.stop()
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="Рейд не найден",
                    description="Похоже, запись была удалена.",
                    color=discord.Color.dark_grey(),
                ),
                view=None,
            )
            return

        specs = self.bot.store.specs_for_role(raid["guild_id"], role)
        if not specs:
            warning = (
                f"Для роли «{ROLE_LABELS[role]}» пока нет специализаций. "
                "Администратору нужно добавить их командой /специализация добавить."
            )
            new_view = RoleSelectView(
                self.bot, self.raid_id, self.user_id, warning=warning
            )
            await self._move_to(interaction, new_view, raid)
            return

        new_view = SpecSelectView(self.bot, self.raid_id, self.user_id, role)
        await self._move_to(interaction, new_view, raid)


class SpecSelectView(WizardView):
    def __init__(
        self,
        bot: Any,
        raid_id: str,
        user_id: int,
        role: str,
        *,
        warning: str | None = None,
    ) -> None:
        super().__init__(bot, raid_id, user_id)
        self.role = role
        self.warning = warning

        raid = bot.store.get_raid(raid_id) or {}
        current = _current_registration(raid, user_id) or {}
        current_spec_id = current.get("spec_id")
        specs = bot.store.specs_for_role(raid.get("guild_id"), role)[
            :MAX_SPECS_PER_ROLE
        ]

        options = [
            discord.SelectOption(
                label=spec["name"][:100],
                value=spec["id"],
                emoji=to_partial_emoji(spec.get("emoji", "")),
                default=(spec["id"] == current_spec_id),
            )
            for spec in specs
        ]

        select = discord.ui.Select(
            placeholder="Выберите специализацию",
            min_values=1,
            max_values=1,
            options=options,
        )
        select.callback = self._on_spec  # type: ignore[method-assign]
        self.add_item(select)

        back = discord.ui.Button(
            label="Назад", style=discord.ButtonStyle.secondary
        )
        back.callback = self._back  # type: ignore[method-assign]
        self.add_item(back)
        self.add_item(self._cancel_button())

    def build_embed(self, raid: dict[str, Any]) -> discord.Embed:
        role_emoji = str(raid.get("role_emojis", {}).get(self.role, "")).strip()
        lines = [
            "**Шаг 2 из 3 · Специализация**",
            f"Роль: {role_emoji} **{ROLE_LABELS[self.role]}**".strip(),
            "Выберите вашу специализацию.",
        ]
        if self.warning:
            lines.extend(("", f"⚠️ {self.warning}"))
        return _wizard_embed(raid, "Регистрация на рейд", "\n".join(lines))

    async def _back(self, interaction: discord.Interaction) -> None:
        raid = self.bot.store.get_raid(self.raid_id)
        if raid is None:
            await self._cancel(interaction)
            return
        new_view = RoleSelectView(self.bot, self.raid_id, self.user_id)
        await self._move_to(interaction, new_view, raid)

    async def _on_spec(self, interaction: discord.Interaction) -> None:
        assert isinstance(interaction.data, dict)
        values = interaction.data.get("values") or []
        if not values:
            return

        spec_id = str(values[0])
        raid = self.bot.store.get_raid(self.raid_id)
        if raid is None or not _is_open(raid):
            self.stop()
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="Запись закрыта",
                    description="Этот рейд уже начался или был удалён.",
                    color=discord.Color.dark_grey(),
                ),
                view=None,
            )
            return

        spec = next(
            (
                candidate
                for candidate in self.bot.store.specs_for_role(
                    raid["guild_id"], self.role
                )
                if candidate["id"] == spec_id
            ),
            None,
        )
        if spec is None:
            warning = "Эта специализация больше недоступна. Выберите другую."
            new_view = RoleSelectView(
                self.bot, self.raid_id, self.user_id, warning=warning
            )
            await self._move_to(interaction, new_view, raid)
            return

        new_view = StatusView(
            self.bot, self.raid_id, self.user_id, self.role, spec
        )
        await self._move_to(interaction, new_view, raid)


class StatusView(WizardView):
    def __init__(
        self,
        bot: Any,
        raid_id: str,
        user_id: int,
        role: str,
        spec: dict[str, Any],
    ) -> None:
        super().__init__(bot, raid_id, user_id)
        self.role = role
        self.spec = spec

        self._add_status_button(
            "Присоединиться", "✅", discord.ButtonStyle.success, STATUS_MAIN
        )
        self._add_status_button(
            "Скамья запасных", BENCH_EMOJI, discord.ButtonStyle.secondary, STATUS_BENCH
        )
        self._add_status_button(
            "Буду отсутствовать",
            ABSENT_EMOJI,
            discord.ButtonStyle.danger,
            STATUS_ABSENT,
        )

        back = discord.ui.Button(
            label="Назад",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        back.callback = self._back  # type: ignore[method-assign]
        self.add_item(back)

        cancel = discord.ui.Button(
            label="Отмена",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        cancel.callback = self._cancel  # type: ignore[method-assign]
        self.add_item(cancel)

    def _add_status_button(
        self,
        label: str,
        emoji: str,
        style: discord.ButtonStyle,
        status: str,
    ) -> None:
        button = discord.ui.Button(label=label, emoji=emoji, style=style, row=0)
        button.callback = functools.partial(self._set_status, status=status)  # type: ignore[method-assign]
        self.add_item(button)

    def build_embed(self, raid: dict[str, Any]) -> discord.Embed:
        limit = int(raid.get("limits", {}).get(self.role, 0))
        occupied_by_others = count_main_for_role(
            raid, self.role, exclude_user_id=str(self.user_id)
        )
        free_slots = max(0, limit - occupied_by_others)
        role_emoji = str(raid.get("role_emojis", {}).get(self.role, "")).strip()
        spec_emoji = str(self.spec.get("emoji") or "").strip()

        lines = [
            "**Шаг 3 из 3 · Статус**",
            f"Роль: {role_emoji} **{ROLE_LABELS[self.role]}**".strip(),
            f"Специализация: {spec_emoji} **{self.spec['name']}**".strip(),
            f"Свободно мест в основном составе: **{free_slots}/{limit}**.",
        ]

        if free_slots <= 0:
            lines.extend(
                (
                    "",
                    "⚠️ Основной состав этой роли заполнен. Кнопка "
                    "«Присоединиться» переведёт вас в скамью запасных.",
                )
            )

        lines.extend(
            (
                "",
                "Выберите статус участия.",
            )
        )
        return _wizard_embed(raid, "Регистрация на рейд", "\n".join(lines))

    async def _back(self, interaction: discord.Interaction) -> None:
        raid = self.bot.store.get_raid(self.raid_id)
        if raid is None or not _is_open(raid):
            await self._cancel(interaction)
            return
        new_view = SpecSelectView(
            self.bot, self.raid_id, self.user_id, self.role
        )
        await self._move_to(interaction, new_view, raid)

    async def _set_status(
        self, interaction: discord.Interaction, *, status: str
    ) -> None:
        self.stop()

        raid = self.bot.store.get_raid(self.raid_id)
        if raid is None:
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="Рейд не найден",
                    description="Похоже, запись была удалена.",
                    color=discord.Color.dark_grey(),
                ),
                view=None,
            )
            return

        if not _is_open(raid):
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="Запись закрыта",
                    description="Рейд уже начался, изменить запись нельзя.",
                    color=discord.Color.dark_grey(),
                ),
                view=None,
            )
            return

        effective_status, redirected = resolve_requested_status(
            raid, self.user_id, self.role, status
        )

        await interaction.response.defer()

        display_name = getattr(
            interaction.user, "display_name", interaction.user.name
        )
        self.bot.store.set_registration(
            self.raid_id,
            self.user_id,
            role=self.role,
            spec_id=str(self.spec["id"]),
            spec_name=str(self.spec["name"]),
            spec_emoji=str(self.spec.get("emoji") or ""),
            display_name=str(display_name),
            status=effective_status,
        )

        await refresh_raid_panel(self.bot, self.raid_id)

        done = build_done_embed(
            raid=raid,
            role=self.role,
            spec=self.spec,
            status=effective_status,
            redirected=redirected,
        )
        await interaction.edit_original_response(embed=done, view=None)


def build_done_embed(
    *,
    raid: dict[str, Any],
    role: str,
    spec: dict[str, Any],
    status: str,
    redirected: bool,
) -> discord.Embed:
    role_emoji = str(raid.get("role_emojis", {}).get(role, "")).strip()
    spec_emoji = str(spec.get("emoji") or "").strip()

    if status == STATUS_MAIN:
        title = "Вы записаны в основной состав"
        description = "Ваша запись сохранена, эмбед рейда обновлён."
        color = discord.Color.green()
    elif status == STATUS_BENCH:
        title = "Вы в скамье запасных"
        if redirected:
            description = (
                f"Свободных мест в роли «{ROLE_LABELS[role]}» не осталось, "
                "поэтому вы добавлены в скамью запасных."
            )
        else:
            description = "Вы выбрали скамью запасных. Запись сохранена."
        color = discord.Color.orange()
    else:
        title = "Отметка об отсутствии сохранена"
        description = (
            "Вы не будете упомянуты в напоминании за 15 минут до начала рейда."
        )
        color = discord.Color.red()

    embed = discord.Embed(title=title, description=description, color=color)
    embed.add_field(
        name="Роль",
        value=f"{role_emoji} {ROLE_LABELS[role]}".strip(),
        inline=True,
    )
    embed.add_field(
        name="Специализация",
        value=f"{spec_emoji} {spec['name']}".strip(),
        inline=True,
    )
    embed.add_field(
        name="Статус",
        value=STATUS_LABELS[status],
        inline=True,
    )
    embed.set_footer(
        text="Изменить запись можно повторным нажатием «Зарегистрироваться»."
    )
    return embed


async def post_raid_panel(
    bot: Any, channel: discord.abc.Messageable, raid: dict[str, Any]
) -> discord.Message:
    view = RaidPanelView(bot, raid["id"])
    message = await channel.send(embed=build_raid_embed(raid), view=view)
    bot.add_view(view, message_id=message.id)
    return message


async def refresh_raid_panel(bot: Any, raid_id: str) -> bool:
    raid = bot.store.get_raid(raid_id)
    if raid is None or raid.get("message_id") is None:
        return False

    try:
        channel_id = int(raid["channel_id"])
        message_id = int(raid["message_id"])
        channel = bot.get_channel(channel_id)
        if channel is None:
            channel = await bot.fetch_channel(channel_id)
        message = await channel.fetch_message(message_id)

        view = RaidPanelView(bot, raid_id)
        bot.add_view(view, message_id=message_id)
        await message.edit(embed=build_raid_embed(raid), view=view)
        return True
    except (discord.DiscordException, ValueError, TypeError):
        log.exception("Не удалось обновить публичный эмбед рейда %s", raid_id)
        return False
