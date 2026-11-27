from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from raidbot.gacha_exchange import (
    GachaExchangeAmountModal,
    GachaExchangeView,
)
from raidbot.store import Store


class FakeBot:
    def __init__(self, store: Store) -> None:
        self.store = store


class GachaExchangeStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "store.json"
        self.store = Store(self.path)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _add_inventory(self, item_ids: list[str]) -> None:
        self.store.complete_gacha_pull(
            1,
            10,
            cost=0,
            item_ids=item_ids,
            pity=0,
            core_pity=0,
        )

    def test_exchange_duplicate_keeps_one_copy(self) -> None:
        self._add_inventory(["griby", "griby", "griby"])

        profile, item, quantity, gained = (
            self.store.exchange_gacha_duplicates(1, 10, "griby", 2)
        )

        self.assertEqual(item["id"], "griby")
        self.assertEqual(quantity, 2)
        self.assertEqual(gained, 16)
        self.assertEqual(profile["balance"], 16)
        self.assertEqual(profile["inventory"]["griby"], 1)

        with self.assertRaises(ValueError):
            self.store.exchange_gacha_duplicates(1, 10, "griby", 1)

    def test_exchange_all_duplicates(self) -> None:
        self._add_inventory(
            [
                "griby",
                "griby",
                "griby",
                "bolshoy-kamen-nastroyki",
                "bolshoy-kamen-nastroyki",
            ]
        )

        profile, total, breakdown = (
            self.store.exchange_all_gacha_duplicates(1, 10)
        )

        self.assertEqual(total, 2 * 8 + 1 * 35)
        self.assertEqual(profile["balance"], 51)
        self.assertEqual(profile["inventory"]["griby"], 1)
        self.assertEqual(profile["inventory"]["bolshoy-kamen-nastroyki"], 1)
        self.assertEqual(len(breakdown), 2)

    def test_exchange_deleted_item_is_rejected(self) -> None:
        self._add_inventory(["griby", "griby"])
        self.store.delete_gacha_item(1, "griby")

        with self.assertRaises(ValueError):
            self.store.exchange_gacha_duplicates(1, 10, "griby", 1)


class GachaExchangeViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_exchange_view_and_modal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary) / "store.json")
            bot = FakeBot(store)
            store.complete_gacha_pull(
                1,
                10,
                cost=0,
                item_ids=["griby", "griby", "griby"],
                pity=0,
                core_pity=0,
            )

            view = GachaExchangeView(bot, 1, 10)
            embed = view.build_embed()
            self.assertIn("Курс", embed.description)
            self.assertIn("только дубликаты", embed.description)
            select = next(
                item
                for item in view.children
                if hasattr(item, "options")
            )
            self.assertEqual(select.options[0].value, "griby")

            view.message = SimpleNamespace(id=1)
            modal = GachaExchangeAmountModal(
                bot,
                1,
                10,
                "griby",
                "Грибы",
                2,
                8,
                view,
            )
            modal.quantity_input._value = "2"
            response = SimpleNamespace(
                edit_message=AsyncMock(),
                send_message=AsyncMock(),
            )
            interaction = SimpleNamespace(
                message=SimpleNamespace(id=1),
                response=response,
            )

            await modal.on_submit(interaction)

            profile = store.profile_for(1, 10)
            self.assertEqual(profile["balance"], 16)
            self.assertEqual(profile["inventory"]["griby"], 1)
            response.edit_message.assert_awaited_once()
            embed = response.edit_message.await_args.kwargs["embed"]
            self.assertIn("Обменяно", embed.description)

    async def test_close_button_deletes_original_response(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary) / "store.json")
            bot = FakeBot(store)
            view = GachaExchangeView(bot, 1, 10)
            response = SimpleNamespace(
                is_done=lambda: False,
                defer=AsyncMock(),
            )
            interaction = SimpleNamespace(
                response=response,
                delete_original_response=AsyncMock(),
            )

            await view._close(interaction)

            response.defer.assert_awaited_once()
            interaction.delete_original_response.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
