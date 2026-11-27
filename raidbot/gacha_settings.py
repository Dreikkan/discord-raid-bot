from __future__ import annotations

from pathlib import Path
from typing import Any

import discord

from .constants import (
    MAX_GACHA_IMAGE_BYTES,
    MAX_GACHA_IMAGE_URL_LENGTH,
    MAX_GACHA_ITEM_DESCRIPTION_LENGTH,
    MAX_GACHA_ITEM_NAME_LENGTH,
    MAX_GACHA_ITEM_WEIGHT,
)
from .gacha import (
    GACHA_ASSETS_DIR,
    GachaError,
    RARITY_COLORS,
    RARITY_EMOJIS,
    RARITY_LABELS,
    RARITY_ORDER,
    image_reference,
    parse_rarity,
)
from .settings_panel import PANEL_COLOR, PanelView, SettingsView

GACHA_POOL_PAGE_SIZE = 24


class GachaPoolView(PanelView):
    def __init__(self, bot: Any, guild_id: int, *, page: int = 0) -> None:
        super().__init__(bot, guild_id)
        self.page = max(0, int(page))
        items = self.items()
        total_pages = max(
            1, (len(items) + GACHA_POOL_PAGE_SIZE - 1) // GACHA_POOL_PAGE_SIZE
        )
        self.page = min(self.page, total_pages - 1)
        self.total_pages = total_pages
        page_items = items[
            self.page * GACHA_POOL_PAGE_SIZE :
            (self.page + 1) * GACHA_POOL_PAGE_SIZE
        ]

        if page_items:
            options = []
            for item in page_items:
                rarity = str(item.get("rarity") or "common")
                options.append(
                    discord.SelectOption(
                        label=str(item.get("name") or "Без названия")[:100],
                        value=str(item["id"]),
                        description=(
                            f"{RARITY_LABELS.get(rarity, rarity)} · "
                            f"вес {item.get('weight', 100)}"
                        )[:100],
                        emoji=RARITY_EMOJIS.get(rarity, "⚪"),
                    )
                )
            select = discord.ui.Select(
                placeholder="Выберите предмет для настройки",
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

        add = discord.ui.Button(
            label="Добавить предмет",
            emoji="➕",
            style=discord.ButtonStyle.primary,
            row=1,
        )
        add.callback = self._add_item  # type: ignore[method-assign]
        self.add_item(add)

        back = discord.ui.Button(
            label="Назад",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        back.callback = self._back  # type: ignore[method-assign]
        self.add_item(back)

    def items(self) -> list[dict[str, Any]]:
        return self.settings().get("gacha_items", [])

    def build_embed(self) -> discord.Embed:
        items = self.items()
        counts = {
            rarity: sum(
                1 for item in items if item.get("rarity") == rarity
            )
            for rarity in RARITY_ORDER
        }
        composition = "\n".join(
            f"{RARITY_EMOJIS[rarity]} **{RARITY_LABELS[rarity]}:** "
            f"{counts[rarity]}"
            for rarity in RARITY_ORDER
        )
        legendary = [
            str(item.get("name"))
            for item in items
            if item.get("rarity") == "legendary"
        ]

        embed = discord.Embed(
            title="🎁 Предметы гачи",
            description=(
                f"Всего предметов: **{len(items)}**.\n"
                "Выберите предмет в меню, чтобы изменить название, редкость, "
                "описание, вес, картинку или анонс."
            ),
            color=PANEL_COLOR,
        )
        embed.add_field(name="Состав пула", value=composition, inline=False)
        if legendary:
            embed.add_field(
                name="Легендарные",
                value="\n".join(legendary)[:1024],
                inline=False,
            )
        embed.set_footer(
            text=(
                f"Страница {self.page + 1} из {self.total_pages} · "
                "Новые предметы сразу участвуют в крутках."
            )
        )
        return embed

    async def _open_item(self, interaction: discord.Interaction) -> None:
        assert isinstance(interaction.data, dict)
        values = interaction.data.get("values") or []
        if not values:
            return
        item = self.bot.store.find_gacha_item(
            self.guild_id, str(values[0])
        )
        if item is None:
            await interaction.response.send_message(
                "Предмет не найден.", ephemeral=True
            )
            return
        await self.show_view(
            interaction,
            GachaItemView(self.bot, self.guild_id, str(item["id"])),
        )

    async def _previous(self, interaction: discord.Interaction) -> None:
        if self.page <= 0:
            await interaction.response.defer()
            return
        await self.show_view(
            interaction,
            GachaPoolView(self.bot, self.guild_id, page=self.page - 1),
        )

    async def _next(self, interaction: discord.Interaction) -> None:
        if self.page >= self.total_pages - 1:
            await interaction.response.defer()
            return
        await self.show_view(
            interaction,
            GachaPoolView(self.bot, self.guild_id, page=self.page + 1),
        )

    async def _add_item(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            AddGachaItemModal(self.bot, self.guild_id, self)
        )

    async def _back(self, interaction: discord.Interaction) -> None:
        await self.show_view(
            interaction, SettingsView(self.bot, self.guild_id)
        )


class GachaItemView(PanelView):
    def __init__(self, bot: Any, guild_id: int, item_id: str) -> None:
        super().__init__(bot, guild_id)
        self.item_id = str(item_id)

        for label, emoji, callback in (
            ("Название", "🏷️", self._edit_name),
            ("Редкость", "🌟", self._edit_rarity),
            ("Описание", "📝", self._edit_description),
            ("Вес", "⚖️", self._edit_weight),
            ("Картинка", "🖼️", self._edit_image),
        ):
            button = discord.ui.Button(
                label=label,
                emoji=emoji,
                style=discord.ButtonStyle.secondary,
                row=0,
            )
            button.callback = callback
            self.add_item(button)

        announce = discord.ui.Button(
            label="Анонс",
            emoji="📣",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        announce.callback = self._toggle_announce  # type: ignore[method-assign]
        self.add_item(announce)

        delete = discord.ui.Button(
            label="Удалить",
            emoji="🗑️",
            style=discord.ButtonStyle.danger,
            row=1,
        )
        delete.callback = self._delete  # type: ignore[method-assign]
        self.add_item(delete)

        back = discord.ui.Button(
            label="Назад",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        back.callback = self._back  # type: ignore[method-assign]
        self.add_item(back)

    def item(self) -> dict[str, Any] | None:
        return self.bot.store.find_gacha_item(self.guild_id, self.item_id)

    def build_embed(self) -> discord.Embed:
        item = self.item()
        if item is None:
            return discord.Embed(
                title="Предмет не найден", color=discord.Color.red()
            )
        rarity = str(item.get("rarity") or "common")
        image_url, path = image_reference(item)
        if path is not None:
            image_status = "файл загружен"
        elif item.get("image_url"):
            image_status = "ссылка"
        elif item.get("image"):
            image_status = "файл не найден"
        else:
            image_status = "не задана"

        embed = discord.Embed(
            title=(
                f"{RARITY_EMOJIS.get(rarity, '⚪')} "
                f"{item.get('name', 'Предмет')}"
            ),
            description=(
                str(item.get("description") or "").strip()
                or "*Описание не задано.*"
            ),
            color=RARITY_COLORS.get(rarity, PANEL_COLOR),
        )
        embed.add_field(
            name="Редкость",
            value=RARITY_LABELS.get(rarity, rarity),
            inline=True,
        )
        embed.add_field(
            name="Вес",
            value=str(item.get("weight", 100)),
            inline=True,
        )
        embed.add_field(
            name="Анонс",
            value="включён" if item.get("announce") else "выключен",
            inline=True,
        )
        embed.add_field(
            name="Картинка",
            value=image_status,
            inline=False,
        )
        if image_url:
            embed.set_image(url=image_url)
        embed.set_footer(text=f"ID: {item.get('id')}")
        return embed

    def build_files(self) -> list[discord.File]:
        item = self.item()
        if item is None:
            return []
        _, path = image_reference(item)
        if path is None:
            return []
        return [discord.File(path, filename=path.name)]

    async def _edit_name(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            GachaItemNameModal(
                self.bot, self.guild_id, self.item_id, self
            )
        )

    async def _edit_rarity(self, interaction: discord.Interaction) -> None:
        await self.show_view(
            interaction,
            GachaItemRarityView(self.bot, self.guild_id, self.item_id),
        )

    async def _edit_description(
        self, interaction: discord.Interaction
    ) -> None:
        await interaction.response.send_modal(
            GachaItemDescriptionModal(
                self.bot, self.guild_id, self.item_id, self
            )
        )

    async def _edit_weight(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            GachaItemWeightModal(
                self.bot, self.guild_id, self.item_id, self
            )
        )

    async def _edit_image(self, interaction: discord.Interaction) -> None:
        await self.show_view(
            interaction,
            GachaItemImageSourceView(
                self.bot, self.guild_id, self.item_id
            ),
        )

    async def _toggle_announce(
        self, interaction: discord.Interaction
    ) -> None:
        item = self.item()
        if item is None:
            await interaction.response.send_message(
                "Предмет не найден.", ephemeral=True
            )
            return
        item["announce"] = not bool(item.get("announce"))
        try:
            self.bot.store.save_gacha_item(self.guild_id, item)
        except GachaError as exc:
            await interaction.response.send_message(
                f"❌ {exc}", ephemeral=True
            )
            return
        await self.show_view(
            interaction,
            GachaItemView(self.bot, self.guild_id, self.item_id),
        )

    async def _delete(self, interaction: discord.Interaction) -> None:
        await self.show_view(
            interaction,
            GachaItemDeleteView(self.bot, self.guild_id, self.item_id),
        )

    async def _back(self, interaction: discord.Interaction) -> None:
        await self.show_view(
            interaction, GachaPoolView(self.bot, self.guild_id)
        )


class GachaItemRarityView(PanelView):
    def __init__(self, bot: Any, guild_id: int, item_id: str) -> None:
        super().__init__(bot, guild_id)
        self.item_id = str(item_id)
        item = self.item()
        current = str(item.get("rarity")) if item else "common"

        select = discord.ui.Select(
            placeholder="Выберите редкость",
            options=[
                discord.SelectOption(
                    label=RARITY_LABELS[rarity],
                    value=rarity,
                    emoji=RARITY_EMOJIS[rarity],
                    default=rarity == current,
                )
                for rarity in RARITY_ORDER
            ],
            min_values=1,
            max_values=1,
            row=0,
        )
        select.callback = self._on_rarity  # type: ignore[method-assign]
        self.add_item(select)

        back = discord.ui.Button(
            label="Назад",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        back.callback = self._back  # type: ignore[method-assign]
        self.add_item(back)

    def item(self) -> dict[str, Any] | None:
        return self.bot.store.find_gacha_item(self.guild_id, self.item_id)

    def build_embed(self) -> discord.Embed:
        item = self.item()
        if item is None:
            return discord.Embed(
                title="Предмет не найден", color=discord.Color.red()
            )
        rarity = str(item.get("rarity") or "common")
        return discord.Embed(
            title=f"Редкость: {item.get('name', 'Предмет')}",
            description=(
                f"Текущая редкость: {RARITY_EMOJIS.get(rarity, '⚪')} "
                f"**{RARITY_LABELS.get(rarity, rarity)}**\n"
                "Выберите новую редкость."
            ),
            color=RARITY_COLORS.get(rarity, PANEL_COLOR),
        )

    async def _on_rarity(self, interaction: discord.Interaction) -> None:
        assert isinstance(interaction.data, dict)
        values = interaction.data.get("values") or []
        if not values:
            return
        item = self.item()
        if item is None:
            await interaction.response.send_message(
                "Предмет не найден.", ephemeral=True
            )
            return
        try:
            item["rarity"] = parse_rarity(str(values[0]))
            self.bot.store.save_gacha_item(self.guild_id, item)
        except GachaError as exc:
            await interaction.response.send_message(
                f"❌ {exc}", ephemeral=True
            )
            return
        await self.show_view(
            interaction,
            GachaItemView(self.bot, self.guild_id, self.item_id),
        )

    async def _back(self, interaction: discord.Interaction) -> None:
        await self.show_view(
            interaction,
            GachaItemView(self.bot, self.guild_id, self.item_id),
        )


class GachaItemImageSourceView(PanelView):
    def __init__(self, bot: Any, guild_id: int, item_id: str) -> None:
        super().__init__(bot, guild_id)
        self.item_id = str(item_id)

        upload = discord.ui.Button(
            label="Загрузить файл",
            emoji="📤",
            style=discord.ButtonStyle.primary,
            row=0,
        )
        upload.callback = self._upload  # type: ignore[method-assign]
        self.add_item(upload)

        link = discord.ui.Button(
            label="Ссылка",
            emoji="🔗",
            style=discord.ButtonStyle.secondary,
            row=0,
        )
        link.callback = self._link  # type: ignore[method-assign]
        self.add_item(link)

        remove = discord.ui.Button(
            label="Удалить картинку",
            emoji="🗑️",
            style=discord.ButtonStyle.danger,
            row=0,
        )
        remove.callback = self._remove  # type: ignore[method-assign]
        self.add_item(remove)

        back = discord.ui.Button(
            label="Назад",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        back.callback = self._back  # type: ignore[method-assign]
        self.add_item(back)

    def item(self) -> dict[str, Any] | None:
        return self.bot.store.find_gacha_item(self.guild_id, self.item_id)

    def build_embed(self) -> discord.Embed:
        item = self.item()
        if item is None:
            return discord.Embed(
                title="Предмет не найден", color=discord.Color.red()
            )
        image_url, path = image_reference(item)
        if path is not None:
            status = "Загруженный файл"
        elif item.get("image_url"):
            status = "Внешняя ссылка"
        elif item.get("image"):
            status = "Файл не найден"
        else:
            status = "Картинка не задана"
        embed = discord.Embed(
            title=f"Картинка: {item.get('name', 'Предмет')}",
            description=(
                f"**Сейчас:** {status}\n\n"
                "Загрузите PNG, JPG, WEBP или GIF либо укажите прямую ссылку. "
                "Картинка показывается в результате крутки, а для предметов "
                "с включённым анонсом — ещё и в публичном оповещении."
            ),
            color=PANEL_COLOR,
        )
        if image_url:
            embed.set_image(url=image_url)
        return embed

    def build_files(self) -> list[discord.File]:
        item = self.item()
        if item is None:
            return []
        _, path = image_reference(item)
        if path is None:
            return []
        return [discord.File(path, filename=path.name)]

    async def _upload(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            GachaItemImageUploadModal(
                self.bot, self.guild_id, self.item_id, self
            )
        )

    async def _link(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            GachaItemImageUrlModal(
                self.bot, self.guild_id, self.item_id, self
            )
        )

    async def _remove(self, interaction: discord.Interaction) -> None:
        item = self.item()
        if item is None:
            await interaction.response.send_message(
                "Предмет не найден.", ephemeral=True
            )
            return
        item["image"] = ""
        item["image_url"] = ""
        try:
            self.bot.store.save_gacha_item(self.guild_id, item)
        except GachaError as exc:
            await interaction.response.send_message(
                f"❌ {exc}", ephemeral=True
            )
            return
        await self.show_view(
            interaction,
            GachaItemView(self.bot, self.guild_id, self.item_id),
        )

    async def _back(self, interaction: discord.Interaction) -> None:
        await self.show_view(
            interaction,
            GachaItemView(self.bot, self.guild_id, self.item_id),
        )


class GachaItemDeleteView(PanelView):
    def __init__(self, bot: Any, guild_id: int, item_id: str) -> None:
        super().__init__(bot, guild_id)
        self.item_id = str(item_id)

        delete = discord.ui.Button(
            label="Да, удалить",
            emoji="🗑️",
            style=discord.ButtonStyle.danger,
            row=0,
        )
        delete.callback = self._delete  # type: ignore[method-assign]
        self.add_item(delete)

        cancel = discord.ui.Button(
            label="Отмена",
            style=discord.ButtonStyle.secondary,
            row=0,
        )
        cancel.callback = self._cancel  # type: ignore[method-assign]
        self.add_item(cancel)

    def item(self) -> dict[str, Any] | None:
        return self.bot.store.find_gacha_item(self.guild_id, self.item_id)

    def build_embed(self) -> discord.Embed:
        item = self.item()
        name = item.get("name") if item else self.item_id
        return discord.Embed(
            title="Удалить предмет?",
            description=(
                f"Предмет **«{name}»** будет удалён из пула.\n"
                "Уже полученные копии останутся в инвентарях игроков, "
                "но новые выпадать не будут."
            ),
            color=discord.Color.red(),
        )

    async def _delete(self, interaction: discord.Interaction) -> None:
        self.bot.store.delete_gacha_item(self.guild_id, self.item_id)
        await self.show_view(
            interaction, GachaPoolView(self.bot, self.guild_id)
        )

    async def _cancel(self, interaction: discord.Interaction) -> None:
        await self.show_view(
            interaction,
            GachaItemView(self.bot, self.guild_id, self.item_id),
        )


class AddGachaItemModal(discord.ui.Modal):
    def __init__(self, bot: Any, guild_id: int, parent: GachaPoolView) -> None:
        super().__init__(title="Новый предмет гачи")
        self.bot = bot
        self.guild_id = int(guild_id)
        self.parent_view = parent

        self.name_input = discord.ui.TextInput(
            label="Название",
            max_length=MAX_GACHA_ITEM_NAME_LENGTH,
            required=True,
        )
        self.rarity_input = discord.ui.TextInput(
            label="Редкость",
            placeholder=(
                "обычная / необычная / редкая / эпическая / легендарная"
            ),
            default="обычная",
            max_length=32,
            required=True,
        )
        self.description_input = discord.ui.TextInput(
            label="Описание",
            style=discord.TextStyle.paragraph,
            max_length=MAX_GACHA_ITEM_DESCRIPTION_LENGTH,
            required=False,
        )
        self.weight_input = discord.ui.TextInput(
            label="Вес",
            default="100",
            max_length=5,
            required=True,
        )
        for item in (
            self.name_input,
            self.rarity_input,
            self.description_input,
            self.weight_input,
        ):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            rarity = parse_rarity(self.rarity_input.value)
            weight = int(self.weight_input.value)
            if not 1 <= weight <= MAX_GACHA_ITEM_WEIGHT:
                raise GachaError(
                    f"Вес должен быть от 1 до {MAX_GACHA_ITEM_WEIGHT}."
                )
            item = {
                "name": self.name_input.value.strip(),
                "description": self.description_input.value.strip(),
                "rarity": rarity,
                "weight": weight,
                "announce": False,
            }
            saved = self.bot.store.save_gacha_item(self.guild_id, item)
        except (GachaError, ValueError) as exc:
            await interaction.response.send_message(
                f"❌ {exc}", ephemeral=True
            )
            return

        await self.parent_view.show_view(
            interaction,
            GachaItemView(self.bot, self.guild_id, str(saved["id"])),
        )


class GachaItemNameModal(discord.ui.Modal):
    def __init__(
        self,
        bot: Any,
        guild_id: int,
        item_id: str,
        parent: GachaItemView,
    ) -> None:
        super().__init__(title="Название предмета")
        self.bot = bot
        self.guild_id = int(guild_id)
        self.item_id = str(item_id)
        self.parent_view = parent
        item = bot.store.find_gacha_item(guild_id, item_id) or {}
        self.name_input = discord.ui.TextInput(
            label="Название",
            default=str(item.get("name") or ""),
            max_length=MAX_GACHA_ITEM_NAME_LENGTH,
            required=True,
        )
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        item = self.bot.store.find_gacha_item(
            self.guild_id, self.item_id
        )
        if item is None:
            await interaction.response.send_message(
                "Предмет не найден.", ephemeral=True
            )
            return
        item["name"] = self.name_input.value.strip()
        try:
            self.bot.store.save_gacha_item(self.guild_id, item)
        except GachaError as exc:
            await interaction.response.send_message(
                f"❌ {exc}", ephemeral=True
            )
            return
        await self.parent_view.show_view(
            interaction,
            GachaItemView(self.bot, self.guild_id, self.item_id),
        )


class GachaItemDescriptionModal(discord.ui.Modal):
    def __init__(
        self,
        bot: Any,
        guild_id: int,
        item_id: str,
        parent: GachaItemView,
    ) -> None:
        super().__init__(title="Описание предмета")
        self.bot = bot
        self.guild_id = int(guild_id)
        self.item_id = str(item_id)
        self.parent_view = parent
        item = bot.store.find_gacha_item(guild_id, item_id) or {}
        self.description_input = discord.ui.TextInput(
            label="Описание",
            style=discord.TextStyle.paragraph,
            default=str(item.get("description") or ""),
            max_length=MAX_GACHA_ITEM_DESCRIPTION_LENGTH,
            required=False,
        )
        self.add_item(self.description_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        item = self.bot.store.find_gacha_item(
            self.guild_id, self.item_id
        )
        if item is None:
            await interaction.response.send_message(
                "Предмет не найден.", ephemeral=True
            )
            return
        item["description"] = self.description_input.value.strip()
        try:
            self.bot.store.save_gacha_item(self.guild_id, item)
        except GachaError as exc:
            await interaction.response.send_message(
                f"❌ {exc}", ephemeral=True
            )
            return
        await self.parent_view.show_view(
            interaction,
            GachaItemView(self.bot, self.guild_id, self.item_id),
        )


class GachaItemWeightModal(discord.ui.Modal):
    def __init__(
        self,
        bot: Any,
        guild_id: int,
        item_id: str,
        parent: GachaItemView,
    ) -> None:
        super().__init__(title="Вес предмета")
        self.bot = bot
        self.guild_id = int(guild_id)
        self.item_id = str(item_id)
        self.parent_view = parent
        item = bot.store.find_gacha_item(guild_id, item_id) or {}
        self.weight_input = discord.ui.TextInput(
            label="Вес",
            default=str(item.get("weight", 100)),
            max_length=5,
            required=True,
        )
        self.add_item(self.weight_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        item = self.bot.store.find_gacha_item(
            self.guild_id, self.item_id
        )
        if item is None:
            await interaction.response.send_message(
                "Предмет не найден.", ephemeral=True
            )
            return
        try:
            weight = int(self.weight_input.value)
            if not 1 <= weight <= MAX_GACHA_ITEM_WEIGHT:
                raise GachaError(
                    f"Вес должен быть от 1 до {MAX_GACHA_ITEM_WEIGHT}."
                )
        except (GachaError, ValueError) as exc:
            await interaction.response.send_message(
                f"❌ {exc}", ephemeral=True
            )
            return
        item["weight"] = weight
        try:
            self.bot.store.save_gacha_item(self.guild_id, item)
        except GachaError as exc:
            await interaction.response.send_message(
                f"❌ {exc}", ephemeral=True
            )
            return
        await self.parent_view.show_view(
            interaction,
            GachaItemView(self.bot, self.guild_id, self.item_id),
        )


class GachaItemImageUrlModal(discord.ui.Modal):
    def __init__(
        self,
        bot: Any,
        guild_id: int,
        item_id: str,
        parent: GachaItemImageSourceView,
    ) -> None:
        super().__init__(title="Ссылка на картинку")
        self.bot = bot
        self.guild_id = int(guild_id)
        self.item_id = str(item_id)
        self.parent_view = parent
        item = bot.store.find_gacha_item(guild_id, item_id) or {}
        self.url_input = discord.ui.TextInput(
            label="Прямая ссылка",
            placeholder="https://example.com/image.png",
            default=str(item.get("image_url") or ""),
            max_length=MAX_GACHA_IMAGE_URL_LENGTH,
            required=True,
        )
        self.add_item(self.url_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        url = self.url_input.value.strip()
        if not url.startswith(("http://", "https://")):
            await interaction.response.send_message(
                "❌ Ссылка должна начинаться с http:// или https://.",
                ephemeral=True,
            )
            return
        item = self.bot.store.find_gacha_item(
            self.guild_id, self.item_id
        )
        if item is None:
            await interaction.response.send_message(
                "Предмет не найден.", ephemeral=True
            )
            return
        item["image_url"] = url
        item["image"] = ""
        try:
            self.bot.store.save_gacha_item(self.guild_id, item)
        except GachaError as exc:
            await interaction.response.send_message(
                f"❌ {exc}", ephemeral=True
            )
            return
        await self.parent_view.show_view(
            interaction,
            GachaItemView(self.bot, self.guild_id, self.item_id),
        )


class GachaItemImageUploadModal(discord.ui.Modal):
    def __init__(
        self,
        bot: Any,
        guild_id: int,
        item_id: str,
        parent: GachaItemImageSourceView,
    ) -> None:
        super().__init__(title="Загрузка картинки")
        self.bot = bot
        self.guild_id = int(guild_id)
        self.item_id = str(item_id)
        self.parent_view = parent
        self.upload = discord.ui.FileUpload(
            required=True, min_values=1, max_values=1
        )
        self.add_item(
            discord.ui.Label(
                text="Картинка предмета",
                description="PNG, JPG, WEBP или GIF",
                component=self.upload,
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        attachments = self.upload.values
        if not attachments:
            await interaction.response.send_message(
                "❌ Файл не получен.", ephemeral=True
            )
            return
        attachment = attachments[0]
        if attachment.size > MAX_GACHA_IMAGE_BYTES:
            await interaction.response.send_message(
                "❌ Файл слишком большой. Максимум "
                f"{MAX_GACHA_IMAGE_BYTES // (1024 * 1024)} МБ.",
                ephemeral=True,
            )
            return
        suffix = Path(attachment.filename or "").suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            await interaction.response.send_message(
                "❌ Поддерживаются только PNG, JPG, WEBP и GIF.",
                ephemeral=True,
            )
            return

        item = self.bot.store.find_gacha_item(
            self.guild_id, self.item_id
        )
        if item is None:
            await interaction.response.send_message(
                "Предмет не найден.", ephemeral=True
            )
            return

        try:
            data = await attachment.read()
        except discord.DiscordException:
            await interaction.response.send_message(
                "❌ Не удалось прочитать файл.", ephemeral=True
            )
            return

        try:
            GACHA_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
            filename = f"{self.item_id}{suffix}"
            destination = GACHA_ASSETS_DIR / filename
            destination.write_bytes(data)
        except OSError:
            await interaction.response.send_message(
                "❌ Не удалось сохранить картинку на сервере.",
                ephemeral=True,
            )
            return

        old_image = str(item.get("image") or "")
        if old_image and old_image != filename:
            old_path = GACHA_ASSETS_DIR / old_image
            try:
                old_path.unlink()
            except OSError:
                pass

        item["image"] = filename
        item["image_url"] = ""
        try:
            self.bot.store.save_gacha_item(self.guild_id, item)
        except GachaError as exc:
            await interaction.response.send_message(
                f"❌ {exc}", ephemeral=True
            )
            return

        await self.parent_view.show_view(
            interaction,
            GachaItemView(self.bot, self.guild_id, self.item_id),
        )
