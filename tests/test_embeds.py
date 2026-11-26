from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from raidbot.constants import (
    STATUS_ABSENT,
    STATUS_BENCH,
    STATUS_MAIN,
)
from raidbot.embeds import build_raid_embed
from raidbot.store import Store


def make_raid() -> dict:
    return {
        "id": "raid1",
        "title": "Еженедельный рейд",
        "description": "Сбор в Discord.",
        "start_at": 1793033400,
        "limits": {"tank": 2, "heal": 3, "dd": 4},
        "role_emojis": {"tank": "🛡️", "heal": "💚", "dd": "⚔️"},
        "registrations": {
            "1": {
                "role": "tank",
                "status": STATUS_MAIN,
                "spec_name": "Страж",
                "spec_emoji": "🐻",
                "display_name": "Игрок 1",
            },
            "2": {
                "role": "tank",
                "status": STATUS_MAIN,
                "spec_name": "Рыцарь крови",
                "spec_emoji": "🩸",
                "display_name": "Игрок_2",
            },
            "3": {
                "role": "heal",
                "status": STATUS_MAIN,
                "spec_name": "Жрец",
                "spec_emoji": "✨",
                "display_name": "Игрок 3",
            },
            "4": {
                "role": "dd",
                "status": STATUS_BENCH,
                "spec_name": "Маг",
                "spec_emoji": "🔮",
                "display_name": "Игрок 5",
            },
            "5": {
                "role": "dd",
                "status": STATUS_ABSENT,
                "spec_name": "Воин",
                "spec_emoji": "⚔️",
                "display_name": "Игрок 6",
            },
        },
    }


class EmbedTests(unittest.TestCase):
    def test_role_counts_and_spec_icons(self) -> None:
        embed = build_raid_embed(make_raid())

        self.assertEqual(embed.title, "Еженедельный рейд")
        self.assertIn("<t:1793033400:D>", embed.description)
        self.assertIn("Сбор в Discord.", embed.description)

        fields = {field.name: field.value for field in embed.fields}
        self.assertIn("🛡️ Танк: (2/2)", fields)
        self.assertIn("💚 Хил: (1/3)", fields)
        self.assertIn("⚔️ ДД: (0/4)", fields)
        self.assertIn("🐻 Игрок 1", fields["🛡️ Танк: (2/2)"])
        self.assertIn("🩸 Игрок\\_2", fields["🛡️ Танк: (2/2)"])
        self.assertIn("🔮 Игрок 5", fields["🪑 Скамья запасных (1)"])
        self.assertIn("⚔️ Игрок 6", fields["❌ Буду отсутствовать (1)"])

    def test_three_role_columns_and_icon_before_name(self) -> None:
        embed = build_raid_embed(make_raid())
        role_fields = embed.fields[:3]

        self.assertEqual(
            [field.name for field in role_fields],
            [
                "🛡️ Танк: (2/2)",
                "💚 Хил: (1/3)",
                "⚔️ ДД: (0/4)",
            ],
        )
        self.assertTrue(all(field.inline for field in role_fields))

        tank_lines = role_fields[0].value.splitlines()
        self.assertEqual(tank_lines[0], "🐻 Игрок 1")
        self.assertEqual(tank_lines[1], "🩸 Игрок\\_2")
        self.assertTrue(role_fields[2].value == "—")

    def test_absent_player_is_not_in_main_fields(self) -> None:
        embed = build_raid_embed(make_raid())
        fields = {field.name: field.value for field in embed.fields}
        all_main_values = "\n".join(
            value
            for name, value in fields.items()
            if "Танк" in name or "Хил" in name or "ДД" in name
        )
        self.assertNotIn("Игрок 6", all_main_values)

    def test_empty_raid(self) -> None:
        raid = make_raid()
        raid["registrations"] = {}
        embed = build_raid_embed(raid)
        fields = {field.name: field.value for field in embed.fields}
        self.assertEqual(fields["🛡️ Танк: (0/2)"], "—")
        self.assertEqual(fields["🪑 Скамья запасных (0)"], "—")

    def test_embed_total_length_stays_within_discord_limit(self) -> None:
        raid = make_raid()
        registrations = {}
        for index in range(120):
            registrations[str(index)] = {
                "role": "dd",
                "status": STATUS_BENCH,
                "spec_name": "Очень длинная специализация",
                "spec_emoji": "🔮",
                "display_name": f"Очень длинный ник игрока {index}",
            }
        raid["registrations"] = registrations
        embed = build_raid_embed(raid)
        total = len(embed.title or "") + len(embed.description or "")
        total += len(embed.footer.text or "")
        for field in embed.fields:
            total += len(field.name) + len(field.value)
        self.assertLessEqual(total, 6000)
        self.assertTrue(any("…" in field.value for field in embed.fields))

    def test_static_catalog_registration_goes_to_three_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = Store(Path(temporary_directory) / "store.json")
            settings = store.settings_for(1)
            spec = store.specs_for_role(1, "tank")[0]
            raid = store.create_raid(
                guild_id=1,
                channel_id=2,
                created_by=3,
                title=settings["title"],
                description="Тест",
                start_at=2_000_000_000,
                limits=settings["limits"],
                role_emojis=settings["role_emojis"],
            )
            store.set_registration(
                raid["id"],
                777,
                role="tank",
                spec_id=spec["id"],
                spec_name=spec["name"],
                spec_emoji=spec["emoji"],
                display_name="Рейдер",
                status=STATUS_MAIN,
            )
            saved = store.get_raid(raid["id"])
            assert saved is not None
            embed = build_raid_embed(saved)

        role_fields = embed.fields[:3]
        self.assertTrue(all(field.inline for field in role_fields))
        self.assertTrue(role_fields[0].name.startswith("<:tank:"))
        self.assertIn("Танк:", role_fields[0].name)
        self.assertTrue(role_fields[1].name.startswith("<:heal:"))
        self.assertIn("Хил:", role_fields[1].name)
        self.assertTrue(role_fields[2].name.startswith("<:DD:"))
        self.assertIn("ДД:", role_fields[2].name)
        self.assertEqual(role_fields[0].value, f"{spec['emoji']} Рейдер")


if __name__ == "__main__":
    unittest.main()
