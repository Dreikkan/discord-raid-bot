from __future__ import annotations

import tempfile
import unittest
from datetime import date, time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from raidbot.constants import RAID_ROLE_MENTION_ID
from raidbot.date_picker import RaidDatePickerView
from raidbot.store import Store
from raidbot.time_utils import combine_date_time


class FakeResponse:
    def __init__(self) -> None:
        self.defer = AsyncMock()
        self.edit_message = AsyncMock()
        self.send_message = AsyncMock()


class FakeInteraction:
    def __init__(self, values: list[str] | None = None) -> None:
        self.data = {"values": values or []}
        self.response = FakeResponse()
        self.edit_original_response = AsyncMock()


class FakeChannel:
    id = 2

    def __init__(self) -> None:
        self.send = AsyncMock(
            return_value=SimpleNamespace(id=123, jump_url="https://discord.test/123")
        )


class FakeBot:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.add_view = lambda *args, **kwargs: None


class DatePickerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temporary_directory.name) / "store.json")
        self.bot = FakeBot(self.store)
        self.channel = FakeChannel()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def make_view(self, month_anchor: date = date(2030, 1, 1)) -> RaidDatePickerView:
        return RaidDatePickerView(
            bot=self.bot,
            channel=self.channel,
            guild_id=1,
            created_by=3,
            raid_time=time(20, 30),
            time_text="20:30",
            timezone_text="Europe/Moscow",
            month_anchor=month_anchor,
        )

    def test_calendar_has_month_grid_and_date_selects(self) -> None:
        view = self.make_view()
        description = view.build_embed().description or ""

        self.assertIn("Январь 2030", description)
        self.assertIn("Пн Вт Ср Чт Пт Сб Вс", description)
        self.assertIn("20:30", description)

        selects = [item for item in view.children if item.__class__.__name__ == "Select"]
        self.assertEqual(len(selects), 2)
        self.assertEqual(sum(len(select.options) for select in selects), 31)

    async def test_selecting_date_creates_raid_with_role_mention(self) -> None:
        view = self.make_view()
        selected = date(2030, 1, 15)
        interaction = FakeInteraction([selected.isoformat()])

        await view._on_date(interaction)

        interaction.response.defer.assert_awaited_once()
        self.channel.send.assert_awaited_once()
        send_kwargs = self.channel.send.await_args.kwargs
        self.assertEqual(
            send_kwargs["content"],
            f"<@&{RAID_ROLE_MENTION_ID}>",
        )
        self.assertTrue(send_kwargs["allowed_mentions"].roles)
        self.assertFalse(send_kwargs["allowed_mentions"].users)

        raids = self.bot.store.all_raids()
        self.assertEqual(len(raids), 1)
        raid = raids[0]
        self.assertEqual(raid["description"], "")
        self.assertEqual(
            raid["start_at"],
            combine_date_time(selected, time(20, 30), "Europe/Moscow"),
        )
        self.assertEqual(raid["message_id"], "123")

        interaction.edit_original_response.assert_awaited_once()
        edit_kwargs = interaction.edit_original_response.await_args.kwargs
        self.assertIsNone(edit_kwargs["view"])
        self.assertIn("Рейд создан", edit_kwargs["embed"].title)


if __name__ == "__main__":
    unittest.main()
