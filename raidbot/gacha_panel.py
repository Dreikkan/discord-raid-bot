from __future__ import annotations

import logging
from typing import Any

import discord

from .constants import (
    ACTIVITY_REWARD,
    CURRENCY_EMOJI,
    CURRENCY_NAME,
    GACHA_CORE_PITY,
    GACHA_PITY,
    GACHA_SINGLE_COST,
    GACHA_TEN_COST,
    RAID_REWARD_BENCH,
    RAID_REWARD_MAIN,
)
from .gacha import (
    GachaError,
    RARITY_COLORS,
    RARITY_EMOJIS,
    RARITY_LABELS,
    RARITY_ORDER,
    RollResult,
    image_reference,
    rarity_summary,
    roll_gacha,
)
from .gacha_roles import (
    claim_role_rewards,
    role_reward_status,
    role_rewards,
    send_role_reward_notices,
)

log = logging.getLogger(__name__)

GACHA_PANEL_TIMEOUT = 15 * 60
GACHA_RESULT_TIMEOUT = 15 * 60
GACHA_PANEL_COLOR = 0x8E44AD


def format_currency(amount: int) -> str:
    return f"{int(amount):,}".replace(",", " ")


def build_gacha_panel_embed(
    store: Any, guild_id: int, user_id: int
) -> discord.Embed:
    settings = store.settings_for(guild_id)
    profile = store.profile_for(guild_id, user_id)
    items = settings.get("gacha_items", [])
    remaining = max(0, GACHA_PITY - int(profile.get("pity", 0)))
    remaining_core = max(
        0, GACHA_CORE_PITY - int(profile.get("core_pity", 0))
    )
    legendary_names = [
        str(item.get("name"))
        for item in items
        if item.get("rarity") == "legendary"
    ]
    featured = next(
        (
            item
            for item in items
            if str(item.get("id")) == "core-of-harmony"
        ),
        None,
    )

    embed = discord.Embed(
        title="🌟 Гача гармонии",
        description=(
            "Испытайте удачу и соберите коллекцию наград.\n\n"
            f"**Баланс:** {CURRENCY_EMOJI} **{format_currency(profile['balance'])}** "
            f"{CURRENCY_NAME}\n"
            f"**Всего круток:** {profile['total_pulls']}\n"
            f"**До гарантии легендарки:** {remaining} круток\n"
            f"**До гарантии «Ядра»:** {remaining_core} круток"
        ),
        color=GACHA_PANEL_COLOR,
    )
    embed.add_field(
        name="🎲 Одна крутка",
        value=f"**{GACHA_SINGLE_COST}** {CURRENCY_NAME}",
        inline=True,
    )
    embed.add_field(
        name="🎁 Десять круток",
        value=f"**{GACHA_TEN_COST}** {CURRENCY_NAME}",
        inline=True,
    )
    embed.add_field(
        name="✨ Как получить валюту",
        value=(
            f"Рейд: **+{RAID_REWARD_MAIN}** основному составу, "
            f"**+{RAID_REWARD_BENCH}** скамье\n"
            f"Активность: **+{ACTIVITY_REWARD}** за отметку «Я участвую»"
        ),
        inline=False,
    )
    if items:
        embed.add_field(
            name="Пул наград",
            value=(
                f"Предметов: {len(items)} · "
                f"Легендарных: {len(legendary_names)}"
            ),
            inline=False,
        )
    else:
        embed.add_field(
            name="Пул наград",
            value="Пул пуст. Администратор может добавить предметы в `/настройки`.",
            inline=False,
        )

    role_reward_lines = [
        f"**{reward['name']}** — {reward['milestone']} круток · "
        f"{role_reward_status(profile, reward)}"
        for reward in role_rewards()
    ]
    if role_reward_lines:
        embed.add_field(
            name="🎖️ Гарантированные роли",
            value="\n".join(role_reward_lines),
            inline=False,
        )

    footer = "Гача гармонии"
    if featured is not None:
        footer += f" · Легендарная награда: {featured.get('name')}"
    elif legendary_names:
        footer += f" · Легендарная награда: {legendary_names[0]}"
    embed.set_footer(text=footer)
    return embed


def build_gacha_result_embed(
    result: RollResult,
    *,
    profile: dict[str, Any],
    page: int,
    total: int,
    guild: discord.Guild | None = None,
) -> discord.Embed:
    item = result.item
    rarity = str(item.get("rarity") or "common")
    color = RARITY_COLORS.get(rarity, GACHA_PANEL_COLOR)
    rarity_label = RARITY_LABELS.get(rarity, rarity)
    rarity_emoji = RARITY_EMOJIS.get(rarity, "⚪")
    description = str(item.get("description") or "").strip()
    lines = [f"{rarity_emoji} **{rarity_label}**"]
    if description:
        lines.extend(("", description))
    if result.core_pity:
        lines.extend(
            ("", "✨ **Сработала гарантия «Ядра гармонии»!**")
        )
    elif result.pity:
        lines.extend(("", "✨ **Сработала гарантия легендарки!**"))

    embed = discord.Embed(
        title=f"{rarity_emoji} {item.get('name', 'Награда')}",
        description="\n".join(lines),
        color=color,
    )
    embed.add_field(
        name="Баланс",
        value=f"{CURRENCY_EMOJI} {format_currency(profile['balance'])}",
        inline=True,
    )
    embed.add_field(
        name="В коллекции",
        value=f"×{profile.get('inventory', {}).get(str(item.get('id')), 0)}",
        inline=True,
    )
    remaining = max(0, GACHA_PITY - int(profile.get("pity", 0)))
    remaining_core = max(
        0, GACHA_CORE_PITY - int(profile.get("core_pity", 0))
    )
    embed.add_field(
        name="До легендарки",
        value=f"{remaining} круток",
        inline=True,
    )
    embed.add_field(
        name="До «Ядра»",
        value=f"{remaining_core} круток",
        inline=True,
    )

    if total > 1:
        embed.set_footer(
            text=f"Гача гармонии · Результат {page + 1} из {total}"
        )
    else:
        embed.set_footer(text="Гача гармонии")

    image_url, _ = image_reference(item)
    if image_url:
        embed.set_image(url=image_url)
    if guild is not None:
        embed.timestamp = discord.utils.utcnow()
    return embed


def build_legendary_announcement_content(
    user: discord.abc.User, item: dict[str, Any]
) -> str:
    return (
        f"{user.mention} получил из гачи "
        f"**«{item.get('name', 'Ядро гармонии')}»**"
    )


def build_legendary_announcement_embed(
    user: discord.abc.User,
    item: dict[str, Any],
    guild: discord.Guild | None = None,
) -> discord.Embed:
    rarity = str(item.get("rarity") or "legendary")
    color = RARITY_COLORS.get(rarity, 0xF1C40F)
    embed = discord.Embed(
        title="✨ ЛЕГЕНДАРНАЯ НАГРАДА ✨",
        description=(
            "*Невероятная удача!*\n\n"
            f"**{item.get('name', 'Ядро гармонии')}** уже в коллекции."
        ),
        color=color,
    )
    image_url, _ = image_reference(item)
    if image_url:
        embed.set_image(url=image_url)
    footer = "Гача гармонии"
    if guild is not None:
        footer = f"{guild.name} · {footer}"
    embed.set_footer(text=footer)
    embed.timestamp = discord.utils.utcnow()
    return embed


class GachaPanelView(discord.ui.View):
    def __init__(self, bot: Any, guild_id: int, user_id: int) -> None:
        super().__init__(timeout=GACHA_PANEL_TIMEOUT)
        self.bot = bot
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)
        self.message: discord.Message | None = None

        single = discord.ui.Button(
            label="Крутить ×1",
            emoji="🎲",
            style=discord.ButtonStyle.primary,
            row=0,
        )
        single.callback = self._pull_one  # type: ignore[method-assign]
        self.add_item(single)

        ten = discord.ui.Button(
            label="Крутить ×10",
            emoji="🎁",
            style=discord.ButtonStyle.success,
            row=0,
        )
        ten.callback = self._pull_ten  # type: ignore[method-assign]
        self.add_item(ten)

        inventory = discord.ui.Button(
            label="Инвентарь",
            emoji="🎒",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        inventory.callback = self._inventory  # type: ignore[method-assign]
        self.add_item(inventory)

        help_button = discord.ui.Button(
            label="Как получить валюту",
            emoji="✨",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        help_button.callback = self._help  # type: ignore[method-assign]
        self.add_item(help_button)

    def build_embed(self) -> discord.Embed:
        return build_gacha_panel_embed(
            self.bot.store, self.guild_id, self.user_id
        )

    async def on_timeout(self) -> None:
        if self.message is None:
            return
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
            pass

    async def _pull_one(self, interaction: discord.Interaction) -> None:
        await perform_gacha_pull(self.bot, interaction, 1)

    async def _pull_ten(self, interaction: discord.Interaction) -> None:
        await perform_gacha_pull(self.bot, interaction, 10)

    async def _inventory(self, interaction: discord.Interaction) -> None:
        await send_inventory(self.bot, interaction, self.guild_id, self.user_id)

    async def _help(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="✨ Как получить осколки гармонии",
            description=(
                f"**Рейд:** +{RAID_REWARD_MAIN} основному составу и "
                f"+{RAID_REWARD_BENCH} скамье, когда рейд начинается.\n"
                f"**Активность:** +{ACTIVITY_REWARD} за кнопку «Я участвую» "
                "под напоминанием.\n\n"
                "Осколки тратятся на крутки в гаче. Чем больше вы играете, "
                "тем больше у вас попыток собрать коллекцию."
            ),
            color=GACHA_PANEL_COLOR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class GachaResultView(discord.ui.View):
    def __init__(
        self,
        bot: Any,
        guild_id: int,
        user_id: int,
        results: list[RollResult],
        *,
        page: int | None = None,
    ) -> None:
        super().__init__(timeout=GACHA_RESULT_TIMEOUT)
        self.bot = bot
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)
        self.results = results
        if page is None:
            page = 0
            core_index = next(
                (
                    index
                    for index, result in enumerate(results)
                    if str(result.item.get("id")) == "core-of-harmony"
                ),
                None,
            )
            if core_index is not None:
                page = core_index
            else:
                best_rank = -1
                for index, result in enumerate(results):
                    rarity = str(result.item.get("rarity") or "common")
                    rank = (
                        RARITY_ORDER.index(rarity)
                        if rarity in RARITY_ORDER
                        else -1
                    )
                    if rank > best_rank:
                        best_rank = rank
                        page = index
        self.page = max(0, min(int(page), max(0, len(results) - 1)))
        self.message: discord.Message | None = None

        if len(results) > 1:
            previous = discord.ui.Button(
                label="◀",
                style=discord.ButtonStyle.secondary,
                row=0,
            )
            previous.callback = self._previous  # type: ignore[method-assign]
            self.add_item(previous)

            following = discord.ui.Button(
                label="▶",
                style=discord.ButtonStyle.secondary,
                row=0,
            )
            following.callback = self._next  # type: ignore[method-assign]
            self.add_item(following)

        close = discord.ui.Button(
            label="Закрыть",
            style=discord.ButtonStyle.danger,
            row=0,
        )
        close.callback = self._close  # type: ignore[method-assign]
        self.add_item(close)
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        for item in self.children:
            if not isinstance(item, discord.ui.Button):
                continue
            if item.label == "◀":
                item.disabled = self.page <= 0
            elif item.label == "▶":
                item.disabled = self.page >= len(self.results) - 1

    def current(self) -> RollResult:
        return self.results[self.page]

    def profile(self) -> dict[str, Any]:
        return self.bot.store.profile_for(self.guild_id, self.user_id)

    def build_embed(self) -> discord.Embed:
        embed = build_gacha_result_embed(
            self.current(),
            profile=self.profile(),
            page=self.page,
            total=len(self.results),
            guild=self.bot.get_guild(self.guild_id),
        )
        if len(self.results) > 1:
            embed.add_field(
                name="В этой крутке",
                value=rarity_summary(self.results),
                inline=False,
            )
        return embed

    def build_files(self) -> list[discord.File]:
        _, path = image_reference(self.current().item)
        if path is None:
            return []
        return [discord.File(path, filename=path.name)]

    async def on_timeout(self) -> None:
        if self.message is None:
            return
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
            pass

    async def _previous(self, interaction: discord.Interaction) -> None:
        if self.page <= 0:
            await interaction.response.defer()
            return
        self.page -= 1
        await self._render(interaction)

    async def _next(self, interaction: discord.Interaction) -> None:
        if self.page >= len(self.results) - 1:
            await interaction.response.defer()
            return
        self.page += 1
        await self._render(interaction)

    async def _render(self, interaction: discord.Interaction) -> None:
        self._sync_buttons()
        await interaction.response.edit_message(
            embed=self.build_embed(),
            view=self,
            attachments=self.build_files(),
        )

    async def _close(self, interaction: discord.Interaction) -> None:
        self.stop()
        if not interaction.response.is_done():
            await interaction.response.defer()
        try:
            await interaction.delete_original_response()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass


class GachaInventoryView(discord.ui.View):
    PAGE_SIZE = 10

    def __init__(
        self,
        bot: Any,
        guild_id: int,
        user_id: int,
        *,
        page: int = 0,
    ) -> None:
        super().__init__(timeout=GACHA_RESULT_TIMEOUT)
        self.bot = bot
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)
        self.page = max(0, int(page))
        self.message: discord.Message | None = None
        self.entries = self._entries()
        total_pages = max(1, (len(self.entries) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        self.page = min(self.page, total_pages - 1)
        self.total_pages = total_pages
        button_row = 1 if self.entries else 0

        if self.entries:
            start = self.page * self.PAGE_SIZE
            options = [
                discord.SelectOption(
                    label=(
                        f"{item.get('name', 'Награда')} ×{count}"
                    )[:100],
                    value=str(item["id"]),
                    description=(
                        f"{RARITY_LABELS.get(str(item.get('rarity') or 'common'), 'Обычная')} · "
                        "открыть карточку"
                    )[:100],
                    emoji=RARITY_EMOJIS.get(
                        str(item.get("rarity") or "common"), "⚪"
                    ),
                )
                for item, count in self.entries[
                    start : start + self.PAGE_SIZE
                ]
            ]
            select = discord.ui.Select(
                placeholder="Выберите предмет из коллекции",
                options=options,
                min_values=1,
                max_values=1,
                row=0,
            )
            select.callback = self._open_item  # type: ignore[method-assign]
            self.add_item(select)

        if total_pages > 1:
            previous = discord.ui.Button(
                label="◀",
                style=discord.ButtonStyle.secondary,
                row=button_row,
            )
            previous.callback = self._previous  # type: ignore[method-assign]
            self.add_item(previous)
            following = discord.ui.Button(
                label="▶",
                style=discord.ButtonStyle.secondary,
                row=button_row,
            )
            following.callback = self._next  # type: ignore[method-assign]
            self.add_item(following)

        exchange = discord.ui.Button(
            label="Обменять дубликаты",
            emoji="♻️",
            style=discord.ButtonStyle.success,
            row=button_row,
        )
        exchange.callback = self._exchange  # type: ignore[method-assign]
        self.add_item(exchange)

        close = discord.ui.Button(
            label="Закрыть",
            style=discord.ButtonStyle.danger,
            row=button_row,
        )
        close.callback = self._close  # type: ignore[method-assign]
        self.add_item(close)
        self._sync_buttons()

    def _entries(self) -> list[tuple[dict[str, Any], int]]:
        profile = self.bot.store.profile_for(self.guild_id, self.user_id)
        settings = self.bot.store.settings_for(self.guild_id)
        by_id = {
            str(item.get("id")): item
            for item in settings.get("gacha_items", [])
        }
        entries: list[tuple[dict[str, Any], int]] = []
        for item_id, count in profile.get("inventory", {}).items():
            item = by_id.get(str(item_id))
            if item is None:
                item = {
                    "id": item_id,
                    "name": f"Удалённый предмет ({item_id})",
                    "description": "",
                    "rarity": "common",
                }
            entries.append((item, int(count)))
        entries.sort(
            key=lambda entry: (
                RARITY_ORDER.index(entry[0].get("rarity", "common"))
                if entry[0].get("rarity") in RARITY_ORDER
                else len(RARITY_ORDER),
                str(entry[0].get("name", "")).casefold(),
            )
        )
        return entries

    def _sync_buttons(self) -> None:
        for item in self.children:
            if not isinstance(item, discord.ui.Button):
                continue
            if item.label == "◀":
                item.disabled = self.page <= 0
            elif item.label == "▶":
                item.disabled = self.page >= self.total_pages - 1

    def build_embed(self) -> discord.Embed:
        profile = self.bot.store.profile_for(self.guild_id, self.user_id)
        description = (
            f"**Баланс:** {CURRENCY_EMOJI} "
            f"{format_currency(profile['balance'])} {CURRENCY_NAME}"
        )
        start = self.page * self.PAGE_SIZE
        page_entries = self.entries[start : start + self.PAGE_SIZE]
        if page_entries:
            lines = []
            for item, count in page_entries:
                rarity = str(item.get("rarity") or "common")
                emoji = RARITY_EMOJIS.get(rarity, "⚪")
                label = RARITY_LABELS.get(rarity, rarity)
                lines.append(
                    f"{emoji} **{item.get('name', 'Награда')}** ×{count} "
                    f"— *{label}*"
                )
            description += "\n\n" + "\n".join(lines)
        else:
            description += "\n\n*Инвентарь пока пуст.*"

        embed = discord.Embed(
            title="🎒 Инвентарь",
            description=description,
            color=GACHA_PANEL_COLOR,
        )
        if self.total_pages > 1:
            embed.set_footer(
                text=f"Страница {self.page + 1} из {self.total_pages}"
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

    async def _open_item(self, interaction: discord.Interaction) -> None:
        assert isinstance(interaction.data, dict)
        values = interaction.data.get("values") or []
        if not values:
            return
        item_id = str(values[0])
        entry = next(
            (
                (item, count)
                for item, count in self.entries
                if str(item.get("id")) == item_id
            ),
            None,
        )
        if entry is None:
            await interaction.response.send_message(
                "Предмет не найден в инвентаре.", ephemeral=True
            )
            return

        self.stop()
        new_view = GachaInventoryItemView(
            self.bot,
            self.guild_id,
            self.user_id,
            item_id,
            page=self.page,
        )
        await interaction.response.edit_message(
            embed=new_view.build_embed(),
            view=new_view,
            attachments=new_view.build_files(),
        )
        new_view.message = interaction.message

    async def _previous(self, interaction: discord.Interaction) -> None:
        if self.page <= 0:
            await interaction.response.defer()
            return
        self.stop()
        new_view = GachaInventoryView(
            self.bot,
            self.guild_id,
            self.user_id,
            page=self.page - 1,
        )
        await interaction.response.edit_message(
            embed=new_view.build_embed(), view=new_view
        )
        new_view.message = interaction.message

    async def _next(self, interaction: discord.Interaction) -> None:
        if self.page >= self.total_pages - 1:
            await interaction.response.defer()
            return
        self.stop()
        new_view = GachaInventoryView(
            self.bot,
            self.guild_id,
            self.user_id,
            page=self.page + 1,
        )
        await interaction.response.edit_message(
            embed=new_view.build_embed(), view=new_view
        )
        new_view.message = interaction.message

    async def _exchange(self, interaction: discord.Interaction) -> None:
        from .gacha_exchange import send_exchange_view

        await send_exchange_view(
            self.bot, interaction, self.guild_id, self.user_id
        )

    async def _close(self, interaction: discord.Interaction) -> None:
        self.stop()
        if not interaction.response.is_done():
            await interaction.response.defer()
        try:
            await interaction.delete_original_response()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass


def build_inventory_item_embed(
    item: dict[str, Any], count: int
) -> discord.Embed:
    rarity = str(item.get("rarity") or "common")
    embed = discord.Embed(
        title=f"{RARITY_EMOJIS.get(rarity, '⚪')} {item.get('name', 'Награда')}",
        description=(
            str(item.get("description") or "").strip()
            or "*Описание не задано.*"
        ),
        color=RARITY_COLORS.get(rarity, GACHA_PANEL_COLOR),
    )
    embed.add_field(
        name="Редкость",
        value=RARITY_LABELS.get(rarity, rarity),
        inline=True,
    )
    embed.add_field(
        name="В коллекции",
        value=f"×{count}",
        inline=True,
    )
    image_url, _ = image_reference(item)
    if image_url:
        embed.set_image(url=image_url)
    embed.set_footer(text="Коллекция гачи · Нажмите «Поделиться»")
    return embed


def build_shared_item_embed(
    item: dict[str, Any],
    owner: Any,
    count: int,
    guild: discord.Guild | None = None,
) -> discord.Embed:
    rarity = str(item.get("rarity") or "common")
    embed = discord.Embed(
        title=f"{RARITY_EMOJIS.get(rarity, '⚪')} {item.get('name', 'Награда')}",
        description=(
            str(item.get("description") or "").strip()
            or "*Предмет из коллекции гачи.*"
        ),
        color=RARITY_COLORS.get(rarity, GACHA_PANEL_COLOR),
    )
    embed.add_field(
        name="Редкость",
        value=RARITY_LABELS.get(rarity, rarity),
        inline=True,
    )
    embed.add_field(
        name="Владелец",
        value=getattr(owner, "mention", str(owner)),
        inline=True,
    )
    embed.add_field(
        name="В коллекции",
        value=f"×{count}",
        inline=True,
    )
    image_url, _ = image_reference(item)
    if image_url:
        embed.set_image(url=image_url)
    footer = "Коллекция гачи"
    if guild is not None:
        footer = f"{guild.name} · {footer}"
    embed.set_footer(text=footer)
    embed.timestamp = discord.utils.utcnow()
    return embed


class GachaInventoryItemView(discord.ui.View):
    def __init__(
        self,
        bot: Any,
        guild_id: int,
        user_id: int,
        item_id: str,
        *,
        page: int = 0,
    ) -> None:
        super().__init__(timeout=GACHA_RESULT_TIMEOUT)
        self.bot = bot
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)
        self.item_id = str(item_id)
        self.page = max(0, int(page))
        self.message: discord.Message | None = None
        item = self.item()
        count = self.count()
        share = discord.ui.Button(
            label="Поделиться",
            emoji="📣",
            style=discord.ButtonStyle.success,
            row=0,
            disabled=item is None or count <= 0,
        )
        share.callback = self._share  # type: ignore[method-assign]
        self.add_item(share)

        back = discord.ui.Button(
            label="Назад",
            style=discord.ButtonStyle.secondary,
            row=0,
        )
        back.callback = self._back  # type: ignore[method-assign]
        self.add_item(back)

        close = discord.ui.Button(
            label="Закрыть",
            style=discord.ButtonStyle.danger,
            row=0,
        )
        close.callback = self._close  # type: ignore[method-assign]
        self.add_item(close)

    def item(self) -> dict[str, Any] | None:
        return self.bot.store.find_gacha_item(
            self.guild_id, self.item_id
        )

    def count(self) -> int:
        profile = self.bot.store.profile_for(
            self.guild_id, self.user_id
        )
        return int(profile.get("inventory", {}).get(self.item_id, 0))

    def build_embed(self) -> discord.Embed:
        item = self.item()
        if item is None:
            return discord.Embed(
                title="Предмет не найден",
                description="Этот предмет удалён из пула гачи.",
                color=discord.Color.red(),
            )
        return build_inventory_item_embed(item, self.count())

    def build_files(self) -> list[discord.File]:
        item = self.item()
        if item is None:
            return []
        _, path = image_reference(item)
        if path is None:
            return []
        return [discord.File(path, filename=path.name)]

    async def _share(self, interaction: discord.Interaction) -> None:
        item = self.item()
        count = self.count()
        if item is None:
            await interaction.response.send_message(
                "❌ Предмет удалён из пула гачи.", ephemeral=True
            )
            return
        if count <= 0:
            await interaction.response.send_message(
                "❌ Этого предмета больше нет в вашей коллекции.",
                ephemeral=True,
            )
            return
        channel = interaction.channel
        if channel is None:
            await interaction.response.send_message(
                "❌ Не удалось определить канал.", ephemeral=True
            )
            return

        embed = build_shared_item_embed(
            item, interaction.user, count, interaction.guild
        )
        content = (
            f"**{interaction.user.display_name}** делится предметом "
            "из коллекции:"
        )
        allowed_mentions = discord.AllowedMentions(
            everyone=False, roles=False, users=False, replied_user=False
        )
        _, path = image_reference(item)
        try:
            if path is not None:
                await channel.send(
                    content=content,
                    embed=embed,
                    file=discord.File(path, filename=path.name),
                    allowed_mentions=allowed_mentions,
                )
            else:
                await channel.send(
                    content=content,
                    embed=embed,
                    allowed_mentions=allowed_mentions,
                )
        except (discord.DiscordException, ValueError, TypeError):
            log.exception(
                "Не удалось поделиться предметом %s", self.item_id
            )
            await interaction.response.send_message(
                "❌ Не удалось опубликовать предмет в канал. "
                "Проверьте права бота на отправку сообщений и вложений.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "✅ Предмет опубликован в канал.", ephemeral=True
        )

    async def _back(self, interaction: discord.Interaction) -> None:
        self.stop()
        new_view = GachaInventoryView(
            self.bot,
            self.guild_id,
            self.user_id,
            page=self.page,
        )
        await interaction.response.edit_message(
            embed=new_view.build_embed(),
            view=new_view,
            attachments=[],
        )
        new_view.message = interaction.message

    async def _close(self, interaction: discord.Interaction) -> None:
        self.stop()
        if not interaction.response.is_done():
            await interaction.response.defer()
        try:
            await interaction.delete_original_response()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    async def on_timeout(self) -> None:
        if self.message is None:
            return
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
            pass


async def send_inventory(
    bot: Any, interaction: discord.Interaction, guild_id: int, user_id: int
) -> None:
    view = GachaInventoryView(bot, guild_id, user_id)
    if not view.entries:
        await interaction.response.send_message(
            "🎒 Инвентарь пока пуст. Сделайте первую крутку в `/гача`.",
            ephemeral=True,
        )
        return
    await interaction.response.send_message(
        embed=view.build_embed(), view=view, ephemeral=True
    )
    view.message = await interaction.original_response()


async def perform_gacha_pull(
    bot: Any, interaction: discord.Interaction, count: int
) -> None:
    if interaction.guild is None:
        await interaction.response.send_message(
            "Команду нужно использовать на сервере.", ephemeral=True
        )
        return

    guild_id = interaction.guild.id
    user_id = interaction.user.id
    channel = interaction.channel
    bot_member = interaction.guild.me
    if channel is not None and bot_member is not None:
        permissions = channel.permissions_for(bot_member)
        can_send = permissions.send_messages
        if isinstance(channel, discord.Thread):
            can_send = can_send and permissions.send_messages_in_threads
        if not can_send or not permissions.embed_links:
            await interaction.response.send_message(
                "❌ Боту нужны права **Send Messages** и **Embed Links** "
                "в этом канале.",
                ephemeral=True,
            )
            return
        if not permissions.attach_files:
            await interaction.response.send_message(
                "❌ Боту нужно право **Attach Files**, иначе картинки "
                "наград не отправятся. Выдайте его и попробуйте снова.",
                ephemeral=True,
            )
            return

    settings = bot.store.settings_for(guild_id)
    items = settings.get("gacha_items", [])
    if not items:
        await interaction.response.send_message(
            "❌ Пул наград пуст. Администратор должен добавить предметы "
            "в `/настройки`.",
            ephemeral=True,
        )
        return

    profile = bot.store.profile_for(guild_id, user_id)
    cost = GACHA_TEN_COST if count == 10 else GACHA_SINGLE_COST
    if profile["balance"] < cost:
        embed = discord.Embed(
            title="Недостаточно осколков",
            description=(
                f"Нужно **{cost}** {CURRENCY_NAME}, а у вас "
                f"**{format_currency(profile['balance'])}**.\n\n"
                f"Участвуйте в рейдах и отмечайтесь на активностях, "
                "чтобы получать осколки."
            ),
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    try:
        results, final_pity, final_core_pity = roll_gacha(
            items,
            count,
            int(profile.get("pity", 0)),
            core_pity=int(profile.get("core_pity", 0)),
        )
        updated = bot.store.complete_gacha_pull(
            guild_id,
            user_id,
            cost=cost,
            item_ids=[str(result.item["id"]) for result in results],
            pity=final_pity,
            core_pity=final_core_pity,
        )
    except (GachaError, ValueError) as exc:
        await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        return

    view = GachaResultView(
        bot, guild_id, user_id, results
    )
    embed = view.build_embed()
    files = view.build_files()
    if files:
        await interaction.response.send_message(
            embed=embed, view=view, files=files, ephemeral=True
        )
    else:
        await interaction.response.send_message(
            embed=embed, view=view, ephemeral=True
        )
    view.message = await interaction.original_response()

    grants, errors = await claim_role_rewards(
        bot, interaction.guild, user_id, updated
    )
    if interaction.message is not None:
        try:
            await interaction.message.edit(
                embed=build_gacha_panel_embed(
                    bot.store, guild_id, user_id
                )
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
    if grants or errors:
        await send_role_reward_notices(interaction, grants, errors)

    # Public announcement for legendary rewards is intentionally separate
    # from the ephemeral result so it does not reveal the user's inventory.
    for result in results:
        if result.item.get("announce"):
            await send_legendary_announcement(
                bot, interaction, result.item
            )

    # Keep the local variable meaningful for debugging in logs if needed.
    log.debug(
        "Гача: %s круток, пользователь %s, баланс после: %s",
        count,
        user_id,
        updated.get("balance"),
    )


async def send_legendary_announcement(
    bot: Any, interaction: discord.Interaction, item: dict[str, Any]
) -> None:
    channel = interaction.channel
    if channel is None:
        return
    embed = build_legendary_announcement_embed(
        interaction.user, item, interaction.guild
    )
    content = build_legendary_announcement_content(
        interaction.user, item
    )
    _, path = image_reference(item)
    allowed_mentions = discord.AllowedMentions(
        users=True, roles=False, everyone=False, replied_user=False
    )
    try:
        if path is not None:
            await channel.send(
                content=content,
                embed=embed,
                file=discord.File(path, filename=path.name),
                allowed_mentions=allowed_mentions,
            )
        else:
            await channel.send(
                content=content,
                embed=embed,
                allowed_mentions=allowed_mentions,
            )
    except (discord.DiscordException, ValueError, TypeError):
        log.exception(
            "Не удалось отправить оповещение о легендарной награде %s",
            item.get("id"),
        )
