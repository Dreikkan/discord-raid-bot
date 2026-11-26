from __future__ import annotations

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
        self.assertEqual(settings["limits"], {"tank": 2, "heal": 3, "dd": 8})
        self.assertEqual(settings["role_icons_source"], "assets")
        self.assertEqual(len(settings["specs"]), 12)
        self.assertEqual(
            {role: sum(1 for spec in settings["specs"] if spec["role"] == role) for role in ("tank", "heal", "dd")},
            {"tank": 1, "heal": 1, "dd": 10},
        )
        self.assertTrue(all(spec.get("icon_file") for spec in settings["specs"]))

        self.store.set_title(123, "Новый рейд")
        self.store.set_limits(123, {"tank": 1, "heal": 2, "dd": 3})
        self.store.set_timezone(123, "UTC+03:00")

        reloaded = Store(self.path)
        self.assertEqual(reloaded.settings_for(123)["title"], "Новый рейд")
        self.assertEqual(
            reloaded.settings_for(123)["limits"], {"tank": 1, "heal": 2, "dd": 3}
        )
        self.assertEqual(reloaded.settings_for(123)["timezone"], "UTC+03:00")

    def test_add_remove_and_import_specs(self) -> None:
        self.store.import_specs(123, [], replace=True)
        spec, created = self.store.add_spec(123, "heal", "Жрец", "✨")
        self.assertTrue(created)
        self.assertEqual(spec["role"], "heal")

        updated, created = self.store.add_spec(123, "heal", "жрец", "💚")
        self.assertFalse(created)
        self.assertEqual(updated["emoji"], "💚")
        self.assertEqual(len(self.store.settings_for(123)["specs"]), 1)

        counts = self.store.import_specs(
            123,
            [
                {"role": "tank", "name": "Страж", "emoji": "🐻"},
                {"role": "dd", "name": "Маг", "emoji": "🔮"},
            ],
        )
        self.assertEqual(counts, {"tank": 1, "heal": 1, "dd": 1})

        removed = self.store.remove_spec(123, spec["id"])
        self.assertIsNotNone(removed)
        self.assertEqual(len(self.store.settings_for(123)["specs"]), 2)

    def test_import_can_replace(self) -> None:
        self.store.add_spec(123, "heal", "Жрец", "✨")
        self.store.import_specs(
            123,
            [{"role": "dd", "name": "Маг", "emoji": "🔮"}],
            replace=True,
        )
        settings = self.store.settings_for(123)
        self.assertEqual(len(settings["specs"]), 1)
        self.assertEqual(settings["specs"][0]["name"], "Маг")

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
            spec_id="spec1",
            spec_name="Страж",
            spec_emoji="🐻",
            display_name="Игрок",
            status=STATUS_MAIN,
        )
        self.store.set_registration(
            raid["id"],
            11,
            role="dd",
            spec_id="spec2",
            spec_name="Маг",
            spec_emoji="🔮",
            display_name="Второй",
            status=STATUS_BENCH,
        )

        reloaded = Store(self.path)
        saved = reloaded.get_raid(raid["id"])
        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertEqual(saved["message_id"], "99")
        self.assertEqual(saved["registrations"]["10"]["spec_name"], "Страж")
        self.assertEqual(saved["registrations"]["11"]["status"], STATUS_BENCH)

        self.assertEqual(len(reloaded.main_by_role(saved, "tank")), 1)
        self.assertEqual(len(reloaded.bench(saved)), 1)


if __name__ == "__main__":
    unittest.main()
