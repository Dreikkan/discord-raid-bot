from __future__ import annotations

import logging
from typing import Any

import discord

from .constants import (
    CURRENCY_EMOJI,
    CURRENCY_NAME,
    GACHA_EXCHANGE_VALUES,
)
from .gacha import (
    CORE_ITEM_ID,
    RARITY_EMOJIS,
    RARITY_LABELS,
    RARITY_ORDER,
)

log = logging.getLogger(__name__)

EXCHANGE_TIMEOUT = 15 * 60
EXCHANGE_COLOR = 0x8E44AD
EXCHANGE_PAGE_SIZE = 24


def _format_amount(value: int) -> str:
    return f"{int(value):,}".replace(",", " ")


def _value_for(item: dict[str, Any]) -> int:
    return int(GACHA_EXCHANGE_VALUES.get(str(item.get("rarity")), 0))


def _duplicate_entries(
    bot: Any, guild_id: int, user_id: int
) -> tuple[dict[str, Any], list[tuple[dict[str, Any], int, int]]]:
    profile = bot.store.profile_for(guild_id, user_id)
    settings = bot.store.settings_for(guild_id)
    items_by_id = {
        str(item.get("id")): item
        for item in settings.get("gacha_items", [])
    }
    entries: list[tuple[dict[str, Any], int, int]] = []
    for item_id, raw_count in profile.get("inventory", {}).items():
        count = max(0, int(raw_count))
        if count <= 1 or str(item_id) == CORE_ITEM_ID:
            continue
        item = items_by_id.get(str(item_id))
        if item is None:
            continue
        value = _value_for(item)
        if value <= 0:
            continue
        entries.append((item, count, value))

    entries.sort(
        key=lambda entry: (
            RARITY_ORDER.index(entry[0].get("rarity", "common"))
            if entry[0].get("rarity") in RARITY_ORDER
            else len(RARITY_ORDER),
            str(entry[0].get("name", "")).casefold(),
        )
    )
    return profile, entries


class GachaExchangeView(discord.ui.View):
    def __init__(
        self,
        bot: Any,
        guild_id: int,
        user_id: int,
        *,
        page: int = 0,
        notice: str | None = None,
    ) -> None:
        super().__init__(timeout=EXCHANGE_TIMEOUT)
        self.bot = bot
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)
        self.notice = notice
        self.message: discord.Message | None = None
        self.profile, self.entries = _duplicate_entries(
            bot, self.guild_id, self.user_id
        )
        total_pages = max(
            1, (len(self.entries) + EXCHANGE_PAGE_SIZE - 1) // EXCHANGE_PAGE_SIZE
        )
        self.page = min(max(0, int(page)), total_pages - 1)
        self.total_pages = total_pages
        page_entries = self.entries[
            self.page * EXCHANGE_PAGE_SIZE :
            (self.page + 1) * EXCHANGE_PAGE_SIZE
        ]

        if page_entries:
            options = [
                discord.SelectOption(
                    label=(
                        f"{item.get('name', 'Награда')} ×{count}"
                    )[:100],
                    value=str(item["id"]),
                    description=(
                        f"+{value} за копию · доступно {count - 1}"
                    )[:100],
                    emoji=RARITY_EMOJIS.get(
                        str(item.get("rarity") or "common"), "⚪"
                    ),
                )
                for item, count, value in page_entries
            ]
            select = discord.ui.Select(
                placeholder="Выберите предмет для обмена",
                options=options,
                min_values=1,
                max_values=1,
                row=0,
            )
            select.callback = self._on_select  # type: ignore[method-assign]
            self.add_item(select)

        if total_pages > 1:
            previous = discord.ui.Button(
                label="◀",
                style=discord.ButtonStyle.secondary,
                row=1,
            )
            previous.callback = self._previous  # type: ignore[method-assign]
            self.add_item(previous)

            following = discord.ui.Button(
                label="▶",
                style=discord.ButtonStyle.secondary,
                row=1,
            )
            following.callback = self._next  # type: ignore[method-assign]
            self.add_item(following)

        bulk = discord.ui.Button(
            label="Обменять всё",
            emoji="♻️",
            style=discord.ButtonStyle.success,
            row=1,
            disabled=not self.entries,
        )
        bulk.callback = self._exchange_all  # type: ignore[method-assign]
        self.add_item(bulk)

        close = discord.ui.Button(
            label="Закрыть",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        close.callback = self._close  # type: ignore[method-assign]
        self.add_item(close)

    def build_embed(self) -> discord.Embed:
        rate_lines = [
            f"{RARITY_EMOJIS[rarity]} {RARITY_LABELS[rarity]} — "
            f"{_format_amount(GACHA_EXCHANGE_VALUES[rarity])} "
            f"{CURRENCY_EMOJI}"
            for rarity in RARITY_ORDER
        ]
        description = (
            "Можно обменять **только дубликаты**. Одна копия каждого "
            "предмета всегда остаётся в коллекции.\n\n"
            "**«Ядро гармонии» не участвует в обмене — оно только копится.**\n\n"
            "**Курс за одну копию:**\n"
            + "\n".join(rate_lines)
        )
        if self.notice:
            description = f"{self.notice}\n\n{description}"
        if not self.entries:
            description += "\n\n*Дубликатов для обмена нет.*"

        embed = discord.Embed(
            title="♻️ Обмен дубликатов",
            description=description,
            color=EXCHANGE_COLOR,
        )
        if self.entries:
            embed.set_footer(
                text=(
                    f"Страница {self.page + 1} из {self.total_pages} · "
                    f"Предметов с дубликатами: {len(self.entries)}"
                )
            )
        else:
            embed.set_footer(text="Дубликатов для обмена нет")
        return embed

    async def _on_select(self, interaction: discord.Interaction) -> None:
        assert isinstance(interaction.data, dict)
        values = interaction.data.get("values") or []
        if not values:
            return
        item_id = str(values[0])
        entry = next(
            (
                (item, count, value)
                for item, count, value in self.entries
                if str(item.get("id")) == item_id
            ),
            None,
        )
        if entry is None:
            await interaction.response.send_message(
                "Предмет не найден или у вас нет дубликатов.",
                ephemeral=True,
            )
            return
        item, count, value = entry
        await interaction.response.send_modal(
            GachaExchangeAmountModal(
                self.bot,
                self.guild_id,
                self.user_id,
                item_id,
                str(item.get("name") or item_id),
                max(1, count - 1),
                value,
                self,
            )
        )

    async def _exchange_all(self, interaction: discord.Interaction) -> None:
        profile, total, breakdown = self.bot.store.exchange_all_gacha_duplicates(
            self.guild_id, self.user_id
        )
        if not breakdown:
            await self.show(
                interaction,
                notice=(
                    "ℹ️ Дубликатов, доступных для обмена, нет. "
                    "«Ядро гармонии» не участвует."
                ),
            )
            return
        quantity = sum(int(entry["quantity"]) for entry in breakdown)
        await self.show(
            interaction,
            notice=(
                f"✅ Обменяно **{quantity}** дубликатов на "
                f"**{_format_amount(total)}** {CURRENCY_EMOJI} "
                f"{CURRENCY_NAME}.\n"
                f"Новый баланс: **{_format_amount(profile['balance'])}**."
            ),
        )

    async def show(
        self, interaction: discord.Interaction, *, notice: str | None = None
    ) -> None:
        self.stop()
        new_view = GachaExchangeView(
            self.bot,
            self.guild_id,
            self.user_id,
            page=self.page,
            notice=notice,
        )
        await interaction.response.edit_message(
            embed=new_view.build_embed(), view=new_view
        )
        new_view.message = interaction.message

    async def _previous(self, interaction: discord.Interaction) -> None:
        if self.page <= 0:
            await interaction.response.defer()
            return
        self.stop()
        new_view = GachaExchangeView(
            self.bot,
            self.guild_id,
            self.user_id,
            page=self.page - 1,
            notice=self.notice,
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
        new_view = GachaExchangeView(
            self.bot,
            self.guild_id,
            self.user_id,
            page=self.page + 1,
            notice=self.notice,
        )
        await interaction.response.edit_message(
            embed=new_view.build_embed(), view=new_view
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


class GachaExchangeAmountModal(discord.ui.Modal):
    def __init__(
        self,
        bot: Any,
        guild_id: int,
        user_id: int,
        item_id: str,
        item_name: str,
        max_quantity: int,
        value: int,
        parent: GachaExchangeView,
    ) -> None:
        title = f"Обмен: {item_name}"[:45]
        super().__init__(title=title)
        self.bot = bot
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)
        self.item_id = str(item_id)
        self.item_name = item_name
        self.max_quantity = int(max_quantity)
        self.value = int(value)
        self.parent_view = parent
        self.quantity_input = discord.ui.TextInput(
            label="Количество",
            default="1",
            placeholder=(
                f"До {self.max_quantity} копий · +{self.value} за копию"
            )[:100],
            max_length=6,
            required=True,
        )
        self.add_item(self.quantity_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            quantity = int(self.quantity_input.value)
        except ValueError:
            await interaction.response.send_message(
                "❌ Количество должно быть целым числом.",
                ephemeral=True,
            )
            return
        if not 1 <= quantity <= self.max_quantity:
            await interaction.response.send_message(
                "❌ Можно обменять от 1 до "
                f"{self.max_quantity} копий этого предмета.",
                ephemeral=True,
            )
            return

        try:
            profile, item, quantity, gained = (
                self.bot.store.exchange_gacha_duplicates(
                    self.guild_id,
                    self.user_id,
                    self.item_id,
                    quantity,
                )
            )
        except ValueError as exc:
            await interaction.response.send_message(
                f"❌ {exc}", ephemeral=True
            )
            return

        log.info(
            "Пользователь %s обменял %s × %s на %s осколков",
            self.user_id,
            quantity,
            item.get("id"),
            gained,
        )
        await self.parent_view.show(
            interaction,
            notice=(
                f"✅ Обменяно **{quantity}** × **{item.get('name')}** на "
                f"**{_format_amount(gained)}** {CURRENCY_EMOJI} "
                f"{CURRENCY_NAME}.\n"
                f"Новый баланс: **{_format_amount(profile['balance'])}**."
            ),
        )


async def send_exchange_view(
    bot: Any, interaction: discord.Interaction, guild_id: int, user_id: int
) -> None:
    view = GachaExchangeView(bot, guild_id, user_id)
    if not view.entries:
        await interaction.response.send_message(
            "♻️ У вас нет дубликатов, доступных для обмена. "
            "«Ядро гармонии» не участвует в обмене.",
            ephemeral=True,
        )
        return
    await interaction.response.send_message(
        embed=view.build_embed(), view=view, ephemeral=True
    )
    view.message = await interaction.original_response()
