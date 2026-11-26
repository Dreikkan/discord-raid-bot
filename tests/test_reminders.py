from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from raidbot.constants import STATUS_ABSENT, STATUS_BENCH, STATUS_MAIN
from raidbot.reminders import ReminderService


class FakeChannel:
    def __init__(self) -> None:
        self.send = AsyncMock()


class FakeBot:
    def __init__(self, channel: FakeChannel) -> None:
        self.channel = channel

    def get_channel(self, channel_id: int) -> FakeChannel:
        return self.channel


class ReminderTests(unittest.IsolatedAsyncioTestCase):
    async def test_mentions_main_and_bench_but_not_absent(self) -> None:
        channel = FakeChannel()
        bot = FakeBot(channel)
        service = ReminderService(bot)
        raid = {
            "id": "raid1",
            "channel_id": "123",
            "title": "Рейд",
            "start_at": 2_000_000_000,
            "registrations": {
                "1": {"status": STATUS_MAIN},
                "2": {"status": STATUS_MAIN},
                "3": {"status": STATUS_BENCH},
                "4": {"status": STATUS_ABSENT},
            },
        }

        sent = await service._send_reminder(raid)

        self.assertTrue(sent)
        channel.send.assert_awaited_once()
        content = channel.send.await_args.args[0]
        self.assertIn("<@1>", content)
        self.assertIn("<@2>", content)
        self.assertIn("<@3>", content)
        self.assertNotIn("<@4>", content)
        self.assertIn("**Участники:**", content)
        self.assertIn("**Скамья запасных:**", content)

    async def test_empty_raid_still_sends_reminder(self) -> None:
        channel = FakeChannel()
        service = ReminderService(FakeBot(channel))
        raid = {
            "id": "raid2",
            "channel_id": "123",
            "title": "Пустой рейд",
            "start_at": 2_000_000_000,
            "registrations": {},
        }

        sent = await service._send_reminder(raid)

        self.assertTrue(sent)
        content = channel.send.await_args.args[0]
        self.assertIn("**Участники:** —", content)
        self.assertIn("**Скамья запасных:** —", content)


if __name__ == "__main__":
    unittest.main()
