from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from raidbot.constants import (
    RAID_ROLE_MENTION_ID,
    STATUS_ABSENT,
    STATUS_BENCH,
    STATUS_MAIN,
)
from raidbot.reminders import ReminderService
from raidbot.store import Store


class FakeChannel:
    id = 123

    def __init__(self) -> None:
        self.send = AsyncMock(return_value=SimpleNamespace(id=555))
        self.fetch_message = AsyncMock(
            return_value=SimpleNamespace(delete=AsyncMock())
        )


class FakeBot:
    def __init__(self, channel: FakeChannel, store=None) -> None:
        self.channel = channel
        self.store = store

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

        sent = await service._send_raid_reminder(raid)

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

        sent = await service._send_raid_reminder(raid)

        self.assertTrue(sent)
        content = channel.send.await_args.args[0]
        self.assertIn("**Участники:** —", content)
        self.assertIn("**Скамья запасных:** —", content)

    async def test_configured_reminder_has_role_description_and_participants(
        self,
    ) -> None:
        event_at = 2_000_000_000
        channel = FakeChannel()
        store = MagicMock()
        store.all_raids.return_value = [
            {
                "id": "raid1",
                "guild_id": "1",
                "start_at": event_at,
                "registrations": {
                    "1": {"status": STATUS_MAIN},
                    "2": {"status": STATUS_BENCH},
                    "3": {"status": STATUS_ABSENT},
                },
            }
        ]
        bot = FakeBot(channel, store)
        service = ReminderService(bot)
        reminder = {
            "channel_id": "123",
            "role_id": str(RAID_ROLE_MENTION_ID),
            "description": "Сбор в Discord.",
            "delete_after_minutes": 60,
        }

        sent = await service._send_configured_reminder(
            "1", reminder, event_at
        )

        self.assertTrue(sent)
        channel.send.assert_awaited_once()
        content = channel.send.await_args.args[0]
        self.assertTrue(
            content.startswith(f"<@&{RAID_ROLE_MENTION_ID}>")
        )
        self.assertIn("Сбор в Discord.", content)
        self.assertIn("<@1>", content)
        self.assertIn("<@2>", content)
        self.assertNotIn("<@3>", content)
        self.assertTrue(channel.send.await_args.kwargs["allowed_mentions"].roles)
        self.assertTrue(channel.send.await_args.kwargs["allowed_mentions"].users)

        store.schedule_message_deletion.assert_called_once()
        deletion = store.schedule_message_deletion.call_args.kwargs
        self.assertEqual(deletion["channel_id"], 123)
        self.assertEqual(deletion["message_id"], 555)
        self.assertGreater(deletion["delete_at"], 0)

    async def test_due_configured_reminder_is_sent_and_rescheduled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = Store(Path(temporary_directory) / "store.json")
            store.settings_for(1)
            now = int(time.time())
            event_at = now + 600
            store.set_reminder_config(
                1,
                {
                    "frequency": "weekly",
                    "weekday": 2,
                    "time": "20:30",
                    "timezone": "Europe/Moscow",
                    "channel_id": 123,
                    "delete_after_minutes": 60,
                    "role_id": RAID_ROLE_MENTION_ID,
                    "description": "Сбор за 15 минут.",
                    "next_event_at": event_at,
                    "next_fire_at": now - 10,
                },
            )
            channel = FakeChannel()
            service = ReminderService(FakeBot(channel, store))

            configured = await service.check_configured_reminders(now)

            self.assertEqual(configured, {"1"})
            channel.send.assert_awaited_once()
            content = channel.send.await_args.args[0]
            self.assertIn("Сбор за 15 минут.", content)
            self.assertIn(f"<@&{RAID_ROLE_MENTION_ID}>", content)

            reminder = store.settings_for(1)["reminder"]
            self.assertGreater(reminder["next_fire_at"], now)
            self.assertGreater(reminder["next_event_at"], event_at)
            self.assertEqual(len(store.data["scheduled_deletions"]), 1)

    async def test_expired_reminder_message_is_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = Store(Path(temporary_directory) / "store.json")
            now = int(time.time())
            store.schedule_message_deletion(
                channel_id=123, message_id=555, delete_at=now - 1
            )
            channel = FakeChannel()
            service = ReminderService(FakeBot(channel, store))

            await service._cleanup_expired_messages(now)

            channel.fetch_message.assert_awaited_once_with(555)
            channel.fetch_message.return_value.delete.assert_awaited_once()
            self.assertEqual(store.data["scheduled_deletions"], [])


if __name__ == "__main__":
    unittest.main()
