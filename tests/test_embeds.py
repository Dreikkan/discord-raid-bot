from __future__ import annotations

import unittest

from raidbot.constants import (
    STATUS_ABSENT,
    STATUS_BENCH,
    STATUS_MAIN,
)
from raidbot.embeds import build_raid_embed


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
        self.assertIn("🛡️ Танк (2/2)", fields)
        self.assertIn("💚 Хил (1/3)", fields)
        self.assertIn("⚔️ ДД (0/4)", fields)
        self.assertIn("🐻 Игрок 1", fields["🛡️ Танк (2/2)"])
        self.assertIn("🩸 Игрок\\_2", fields["🛡️ Танк (2/2)"])
        self.assertIn("🔮 Игрок 5", fields["🪑 Скамья запасных (1)"])
        self.assertIn("⚔️ Игрок 6", fields["❌ Буду отсутствовать (1)"])

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
        self.assertEqual(fields["🛡️ Танк (0/2)"], "—")
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


if __name__ == "__main__":
    unittest.main()
