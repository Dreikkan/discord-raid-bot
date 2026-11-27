from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from raidbot.gacha_panel import (
    GachaInventoryItemView,
    GachaInventoryView,
    build_shared_item_embed,
)
from raidbot.store import Store


class FakeBot:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.user = None

    def get_guild(self, guild_id: int):
        return None


class GachaShareTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_embed_contains_item_owner_and_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary) / "store.json")
            item = store.find_gacha_item(1, "griby")
            assert item is not None
            owner = SimpleNamespace(
                mention="<@10>", display_name="Игрок"
            )
            guild = SimpleNamespace(name="Сервер")

            embed = build_shared_item_embed(item, owner, 2, guild)

            self.assertIn("Грибы", embed.title)
            self.assertEqual(
                embed.fields[1].value,
                "<@10>",
            )
            self.assertEqual(embed.image.url, "attachment://griby.png")
            self.assertIn("Сервер", embed.footer.text)

    async def test_inventory_item_can_be_shared_without_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary) / "store.json")
            store.complete_gacha_pull(
                1,
                10,
                cost=0,
                item_ids=["griby"],
                pity=0,
                core_pity=0,
            )
            bot = FakeBot(store)

            inventory = GachaInventoryView(bot, 1, 10)
            select = next(
                item
                for item in inventory.children
                if isinstance(item, discord.ui.Select)
            )
            self.assertIn(
                "griby", [option.value for option in select.options]
            )

            view = GachaInventoryItemView(bot, 1, 10, "griby")
            channel = SimpleNamespace(send=AsyncMock())
            response = SimpleNamespace(send_message=AsyncMock())
            interaction = SimpleNamespace(
                channel=channel,
                user=SimpleNamespace(
                    mention="<@10>", display_name="Игрок"
                ),
                guild=SimpleNamespace(name="Сервер"),
                response=response,
            )

            await view._share(interaction)
            await view._share(interaction)

            self.assertEqual(channel.send.await_count, 2)
            self.assertEqual(response.send_message.await_count, 2)
            for call in channel.send.await_args_list:
                self.assertIn("делится предметом", call.kwargs["content"])
                self.assertIn("Игрок", call.kwargs["content"])
                file = call.kwargs.get("file")
                if file is not None:
                    file.close()


if __name__ == "__main__":
    unittest.main()
