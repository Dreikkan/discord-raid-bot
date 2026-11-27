from __future__ import annotations

import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import discord

from raidbot.constants import (
    ACTIVITY_REWARD,
    RAID_ROLE_MENTION_ID,
    STATUS_ABSENT,
    STATUS_BENCH,
    STATUS_MAIN,
)
from raidbot.reminders import ActivityCheckinView, ReminderService
from raidbot.store import Store


class FakeChannel:
    id = 123

    def __init__(self) -> None:
        self.send = AsyncMock(return_value=SimpleNamespace(id=555))
        self.fetch_message = AsyncMock(
            return_value=SimpleNamespace(delete=AsyncMock())
        )


class FakeBot:
    def __init__(self, channel: FakeChannel, store: Store) -> None:
        self.channel = channel
        self.store = store

    def get_channel(self, channel_id: int) -> FakeChannel:
        return self.channel


class ReminderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temporary_directory.name) / "store.json")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    async def test_mentions_main_and_bench_but_not_absent(self) -> None:
        channel = FakeChannel()
        service = ReminderService(FakeBot(channel, self.store))
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
        service = ReminderService(FakeBot(channel, self.store))
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

    async def test_activity_reminder_has_role_and_description(self) -> None:
        now = int(time.time())
        timezone = "Europe/Moscow"
        start = (datetime.now(ZoneInfo(timezone)) + timedelta(minutes=5)).strftime(
            "%H:%M"
        )

        settings = self.store.settings_for(1)
        activity = next(
            item
            for item in settings["activities"]
            if item["name"] == "Вечеринка"
        )
        activity["channel_id"] = 123
        activity["role_id"] = RAID_ROLE_MENTION_ID
        activity["description"] = "Сбор в голосовом канале."
        activity["schedules"] = [
            {"weekday": None, "start": start, "end": "00:00"}
        ]
        saved = self.store.save_activity(1, activity)

        channel = FakeChannel()
        service = ReminderService(FakeBot(channel, self.store))

        await service.check_activity_reminders(now)

        channel.send.assert_awaited_once()
        content = channel.send.await_args.args[0]
        self.assertTrue(
            content.startswith(f"<@&{RAID_ROLE_MENTION_ID}>")
        )
        self.assertIn("Сбор в голосовом канале.", content)
        self.assertIn("Вечеринка", content)
        self.assertIn("Начало:", content)
        self.assertIn("Окончание:", content)

        restored = next(
            item
            for item in self.store.settings_for(1)["activities"]
            if item["id"] == saved["id"]
        )
        self.assertGreater(restored["last_sent_event_at"], now)
        self.assertEqual(len(self.store.data["scheduled_deletions"]), 1)

        await service.check_activity_reminders(int(time.time()) + 1)
        channel.send.assert_awaited_once()

    async def test_expired_reminder_message_is_deleted(self) -> None:
        now = int(time.time())
        self.store.schedule_message_deletion(
            channel_id=123, message_id=555, delete_at=now - 1
        )
        channel = FakeChannel()
        service = ReminderService(FakeBot(channel, self.store))

        await service._cleanup_expired_messages(now)

        channel.fetch_message.assert_awaited_once_with(555)
        channel.fetch_message.return_value.delete.assert_awaited_once()
        self.assertEqual(self.store.data["scheduled_deletions"], [])

    async def test_raid_reminders_are_independent_from_activities(self) -> None:
        now = int(time.time())
        start_at = now + 10 * 60
        raid = self.store.create_raid(
            guild_id=1,
            channel_id=123,
            created_by=2,
            title="Рейд",
            description="",
            start_at=start_at,
            limits={"tank": 1, "heal": 2, "dd": 7},
            role_emojis={
                "tank": "<:tank:1>",
                "heal": "<:heal:2>",
                "dd": "<:DD:3>",
            },
        )
        self.store.set_registration(
            raid["id"],
            10,
            role="tank",
            specializations=[{"id": "power", "name": "Сила", "emoji": "⚔️"}],
            display_name="Танк",
            status=STATUS_MAIN,
        )

        channel = FakeChannel()
        service = ReminderService(FakeBot(channel, self.store))

        await service.check_due_reminders()

        channel.send.assert_awaited_once()
        content = channel.send.await_args.args[0]
        self.assertIn("**Участники:**", content)
        self.assertIn("<@10>", content)

        saved = self.store.get_raid(raid["id"])
        assert saved is not None
        self.assertIsNotNone(saved["notification_sent_at"])

    async def test_activity_reminder_registers_checkin_event(self) -> None:
        now = int(time.time())
        timezone = "Europe/Moscow"
        start = (datetime.now(ZoneInfo(timezone)) + timedelta(minutes=5)).strftime(
            "%H:%M"
        )
        settings = self.store.settings_for(1)
        activity = next(
            item
            for item in settings["activities"]
            if item["name"] == "Вечеринка"
        )
        activity["channel_id"] = 123
        activity["role_id"] = RAID_ROLE_MENTION_ID
        activity["schedules"] = [
            {"weekday": None, "start": start, "end": "00:00"}
        ]
        self.store.save_activity(1, activity)

        channel = FakeChannel()
        service = ReminderService(FakeBot(channel, self.store))
        await service.check_activity_reminders(now)

        event = self.store.activity_event(555)
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event["guild_id"], "1")
        self.assertEqual(event["activity_id"], activity["id"])
        view = channel.send.await_args.kwargs.get("view")
        self.assertIsInstance(view, ActivityCheckinView)

    async def test_checkin_button_awards_currency_once(self) -> None:
        now = int(time.time())
        self.store.register_activity_event(
            555,
            guild_id=1,
            activity_id="party",
            start_at=now - 60,
            end_at=now + 3600,
        )
        view = ActivityCheckinView(FakeBot(FakeChannel(), self.store))
        button = next(
            item
            for item in view.children
            if isinstance(item, discord.ui.Button)
        )
        response = SimpleNamespace(send_message=AsyncMock())
        interaction = SimpleNamespace(
            message=SimpleNamespace(id=555),
            user=SimpleNamespace(id=42),
            response=response,
        )

        await button.callback(interaction)

        self.assertEqual(self.store.profile_for(1, 42)["balance"], ACTIVITY_REWARD)
        embed = response.send_message.await_args.kwargs["embed"]
        self.assertIn("Награда получена", embed.title)
        self.assertIn(f"+{ACTIVITY_REWARD}", embed.description)

        second_response = SimpleNamespace(send_message=AsyncMock())
        second_interaction = SimpleNamespace(
            message=SimpleNamespace(id=555),
            user=SimpleNamespace(id=42),
            response=second_response,
        )
        await button.callback(second_interaction)
        second_embed = second_response.send_message.await_args.kwargs["embed"]
        self.assertIn("уже получена", second_embed.title)
        self.assertEqual(self.store.profile_for(1, 42)["balance"], ACTIVITY_REWARD)

    async def test_raid_rewards_are_awarded_at_start_once(self) -> None:
        now = int(time.time())
        raid = self.store.create_raid(
            guild_id=1,
            channel_id=123,
            created_by=2,
            title="Рейд",
            description="",
            start_at=now - 1,
            limits={"tank": 1, "heal": 2, "dd": 7},
            role_emojis={"tank": "1", "heal": "2", "dd": "3"},
        )
        self.store.set_registration(
            raid["id"],
            10,
            role="tank",
            specializations=[],
            display_name="Танк",
            status=STATUS_MAIN,
        )
        service = ReminderService(FakeBot(FakeChannel(), self.store))

        service.check_raid_rewards(now)
        self.assertEqual(self.store.profile_for(1, 10)["balance"], 50)

        service.check_raid_rewards(now + 1)
        self.assertEqual(self.store.profile_for(1, 10)["balance"], 50)


if __name__ == "__main__":
    unittest.main()
