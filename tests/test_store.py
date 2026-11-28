from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from raidbot.constants import STATUS_BENCH, STATUS_MAIN
from raidbot.store import Store


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "store.json"
        self.store = Store(self.path)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_defaults_and_persistence(self) -> None:
        settings = self.store.settings_for(123)
        self.assertEqual(settings["title"], "Еженедельный рейд")
        self.assertEqual(settings["limits"], {"tank": 0, "heal": 2, "dd": 8})
        self.assertEqual(len(settings["specs"]), 12)
        self.assertTrue(all(spec["emoji"].startswith("<:") for spec in settings["specs"]))
        self.assertEqual(len(settings["activities"]), 4)
        party = next(
            activity
            for activity in settings["activities"]
            if activity["name"] == "Вечеринка"
        )
        self.assertEqual(
            party["schedules"],
            [{"weekday": None, "start": "21:00", "end": "21:30"}],
        )
        self.assertIsNone(party["channel_id"])

        self.store.set_title(123, "Новый рейд")
        self.store.set_limits(123, {"tank": 1, "heal": 2, "dd": 3})
        self.store.set_timezone(123, "UTC+03:00")

        reloaded = Store(self.path)
        self.assertEqual(reloaded.settings_for(123)["title"], "Новый рейд")
        self.assertEqual(
            reloaded.settings_for(123)["limits"], {"tank": 1, "heal": 2, "dd": 3}
        )
        self.assertEqual(reloaded.settings_for(123)["timezone"], "UTC+03:00")

    def test_welcome_settings_defaults_and_persistence(self) -> None:
        settings = self.store.settings_for(123)
        self.assertFalse(settings["welcome"]["enabled"])
        self.assertIsNone(settings["welcome"]["channel_id"])

        saved = self.store.save_welcome(
            123,
            {
                "enabled": True,
                "channel_id": 55,
                "title": "Привет!",
                "message": "Добро пожаловать, {user}!",
            },
        )
        self.assertTrue(saved["enabled"])
        self.assertEqual(saved["channel_id"], 55)

        reloaded = Store(self.path)
        restored = reloaded.settings_for(123)["welcome"]
        self.assertTrue(restored["enabled"])
        self.assertEqual(restored["channel_id"], 55)
        self.assertEqual(restored["title"], "Привет!")
        self.assertEqual(restored["message"], "Добро пожаловать, {user}!")

    def test_welcome_is_disabled_without_channel(self) -> None:
        saved = self.store.save_welcome(123, {"enabled": True})
        self.assertFalse(saved["enabled"])

    def test_activity_config_persists_and_can_be_marked_sent(self) -> None:
        settings = self.store.settings_for(123)
        party = next(
            activity
            for activity in settings["activities"]
            if activity["name"] == "Вечеринка"
        )
        party["channel_id"] = 10
        party["role_id"] = 20
        party["description"] = "Скоро начало."
        saved = self.store.save_activity(123, party)
        self.assertEqual(saved["description"], "Скоро начало.")

        self.store.mark_activity_sent(123, saved["id"], 2_000_000_000)
        reloaded = Store(self.path)
        restored = next(
            activity
            for activity in reloaded.settings_for(123)["activities"]
            if activity["id"] == saved["id"]
        )
        self.assertEqual(restored["channel_id"], 10)
        self.assertEqual(restored["role_id"], 20)
        self.assertEqual(restored["description"], "Скоро начало.")
        self.assertEqual(restored["last_sent_event_at"], 2_000_000_000)

    def test_auto_delete_queue_persists_and_returns_due_messages(self) -> None:
        self.store.schedule_message_deletion(
            channel_id=10, message_id=20, delete_at=1000
        )
        self.store.schedule_message_deletion(
            channel_id=10, message_id=21, delete_at=5000
        )

        due = self.store.pop_due_deletions(1500)
        self.assertEqual([item["message_id"] for item in due], ["20"])

        reloaded = Store(self.path)
        self.assertEqual(
            reloaded.data["scheduled_deletions"],
            [{"channel_id": "10", "message_id": "21", "delete_at": 5000}],
        )

    def test_specializations_are_static_even_if_stored_data_differs(self) -> None:
        settings = self.store.settings_for(123)
        settings["specs"] = []
        self.store.save()

        reloaded = Store(self.path)
        self.assertEqual(len(reloaded.settings_for(123)["specs"]), 12)

    def test_dd_specializations_include_tank_spec(self) -> None:
        dd_specs = self.store.specs_for_role(123, "dd")
        tank_specs = self.store.specs_for_role(123, "tank")
        dd_ids = {spec["id"] for spec in dd_specs}
        tank_ids = {spec["id"] for spec in tank_specs}
        self.assertTrue(tank_ids)
        self.assertTrue(tank_ids <= dd_ids)
        self.assertEqual(len(dd_specs), len(dd_ids))

    def test_old_saved_limits_are_migrated_to_new_defaults(self) -> None:
        old_data = {
            "version": 1,
            "guilds": {
                "123": {
                    "title": "Старый рейд",
                    "limits": {"tank": 2, "heal": 3, "dd": 8},
                    "timezone": "Europe/Moscow",
                }
            },
            "raids": {},
        }
        self.path.write_text(
            json.dumps(old_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        reloaded = Store(self.path)
        settings = reloaded.settings_for(123)
        self.assertEqual(settings["limits"], {"tank": 0, "heal": 2, "dd": 8})
        self.assertEqual(settings["settings_version"], 4)
        self.assertEqual(settings["title"], "Старый рейд")

    def test_version_three_default_limits_migrate_to_new_base(self) -> None:
        old_data = {
            "version": 2,
            "guilds": {
                "123": {
                    "settings_version": 3,
                    "title": "Рейд",
                    "limits": {"tank": 1, "heal": 2, "dd": 7},
                    "timezone": "Europe/Moscow",
                }
            },
            "raids": {},
            "profiles": {},
            "activity_events": {},
        }
        self.path.write_text(
            json.dumps(old_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        reloaded = Store(self.path)
        settings = reloaded.settings_for(123)
        self.assertEqual(settings["limits"], {"tank": 0, "heal": 2, "dd": 8})
        self.assertEqual(settings["settings_version"], 4)

    def test_old_raid_limits_are_migrated_to_new_base(self) -> None:
        old_data = {
            "version": 2,
            "guilds": {},
            "raids": {
                "raid1": {
                    "id": "raid1",
                    "limits": {"tank": 1, "heal": 2, "dd": 7},
                    "registrations": {},
                }
            },
            "profiles": {},
            "activity_events": {},
            "scheduled_deletions": [],
        }
        self.path.write_text(
            json.dumps(old_data, ensure_ascii=False),
            encoding="utf-8",
        )

        reloaded = Store(self.path)
        saved = reloaded.get_raid("raid1")
        assert saved is not None
        self.assertEqual(
            saved["limits"], {"tank": 0, "heal": 2, "dd": 8}
        )

    def make_raid(self) -> dict:
        return self.store.create_raid(
            guild_id=1,
            channel_id=2,
            created_by=3,
            title="Рейд",
            description="",
            start_at=1_800_000_000,
            limits={"tank": 0, "heal": 2, "dd": 8},
            role_emojis={"tank": "🛡️", "heal": "💚", "dd": "⚔️"},
        )

    def add_dd(
        self,
        raid_id: str,
        user_id: int,
        *,
        status: str = STATUS_MAIN,
    ) -> None:
        self.store.set_registration(
            raid_id,
            user_id,
            role="dd",
            specializations=[],
            display_name=f"ДД {user_id}",
            status=status,
        )

    def add_tank(
        self,
        raid_id: str,
        user_id: int,
        *,
        status: str = STATUS_MAIN,
        waiting: bool = False,
    ) -> None:
        self.store.set_registration(
            raid_id,
            user_id,
            role="tank",
            specializations=[],
            display_name=f"Танк {user_id}",
            status=status,
            waiting_for_tank_slot=waiting,
        )

    def test_main_tank_removal_keeps_waiting_tank_benched(self) -> None:
        raid = self.make_raid()
        self.add_tank(raid["id"], 1)
        for user_id in range(10, 17):
            self.add_dd(raid["id"], user_id)
        self.add_tank(raid["id"], 100, status=STATUS_BENCH, waiting=True)

        self.assertTrue(self.store.remove_registration(raid["id"], 1))

        saved = self.store.get_raid(raid["id"])
        assert saved is not None
        self.assertEqual(
            saved["registrations"]["100"]["status"], STATUS_BENCH
        )
        self.assertTrue(
            saved["registrations"]["100"]["waiting_for_tank_slot"]
        )

    def test_main_tank_switching_to_bench_keeps_waiting_tank_benched(
        self,
    ) -> None:
        raid = self.make_raid()
        self.add_tank(raid["id"], 1)
        for user_id in range(10, 17):
            self.add_dd(raid["id"], user_id)
        self.add_tank(raid["id"], 100, status=STATUS_BENCH, waiting=True)

        self.add_tank(raid["id"], 1, status=STATUS_BENCH)

        saved = self.store.get_raid(raid["id"])
        assert saved is not None
        self.assertEqual(
            saved["registrations"]["100"]["status"], STATUS_BENCH
        )
        self.assertTrue(
            saved["registrations"]["100"]["waiting_for_tank_slot"]
        )

    def test_main_dd_removal_promotes_waiting_tank(self) -> None:
        raid = self.make_raid()
        for user_id in range(10, 18):
            self.add_dd(raid["id"], user_id)
        self.add_tank(raid["id"], 100, status=STATUS_BENCH, waiting=True)

        self.assertTrue(self.store.remove_registration(raid["id"], 10))

        saved = self.store.get_raid(raid["id"])
        assert saved is not None
        self.assertEqual(
            saved["registrations"]["100"]["status"], STATUS_MAIN
        )
        self.assertFalse(
            saved["registrations"]["100"]["waiting_for_tank_slot"]
        )

    def test_main_dd_switching_to_bench_promotes_waiting_tank(self) -> None:
        raid = self.make_raid()
        for user_id in range(10, 18):
            self.add_dd(raid["id"], user_id)
        self.add_tank(raid["id"], 100, status=STATUS_BENCH, waiting=True)

        self.add_dd(raid["id"], 10, status=STATUS_BENCH)

        saved = self.store.get_raid(raid["id"])
        assert saved is not None
        self.assertEqual(
            saved["registrations"]["100"]["status"], STATUS_MAIN
        )
        self.assertFalse(
            saved["registrations"]["100"]["waiting_for_tank_slot"]
        )

    def test_raid_and_registration_round_trip(self) -> None:
        raid = self.store.create_raid(
            guild_id=1,
            channel_id=2,
            created_by=3,
            title="Рейд",
            description="Описание",
            start_at=1_800_000_000,
            limits={"tank": 2, "heal": 3, "dd": 8},
            role_emojis={"tank": "🛡️", "heal": "💚", "dd": "⚔️"},
        )
        self.store.set_raid_message(raid["id"], channel_id=2, message_id=99)
        self.store.set_registration(
            raid["id"],
            10,
            role="tank",
            specializations=[
                {"id": "spec1", "name": "Страж", "emoji": "🐻"}
            ],
            display_name="Игрок",
            status=STATUS_MAIN,
        )
        self.store.set_registration(
            raid["id"],
            11,
            role="dd",
            specializations=[
                {"id": "spec2", "name": "Маг", "emoji": "🔮"},
                {"id": "spec3", "name": "Воин", "emoji": "⚔️"},
            ],
            display_name="Второй",
            status=STATUS_BENCH,
        )

        reloaded = Store(self.path)
        saved = reloaded.get_raid(raid["id"])
        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertEqual(saved["message_id"], "99")
        self.assertEqual(
            saved["registrations"]["10"]["specializations"][0]["name"], "Страж"
        )
        self.assertEqual(len(saved["registrations"]["11"]["specializations"]), 2)
        self.assertEqual(saved["registrations"]["11"]["status"], STATUS_BENCH)

        self.assertEqual(len(reloaded.main_by_role(saved, "tank")), 1)
        self.assertEqual(len(reloaded.bench(saved)), 1)


if __name__ == "__main__":
    unittest.main()
