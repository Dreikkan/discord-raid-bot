from __future__ import annotations

import unittest

from raidbot.specs import (
    SpecImportError,
    normalize_emoji,
    parse_specs_payload,
    to_partial_emoji,
)


class SpecImportTests(unittest.TestCase):
    def test_flat_list_format(self) -> None:
        payload = [
            {"role": "tank", "name": "Страж", "emoji": "🐻"},
            {"role": "heal", "name": "Жрец", "emoji": "✨"},
            {"role": "dd", "name": "Маг", "emoji": "🔮"},
        ]
        specs = parse_specs_payload(payload)
        self.assertEqual(len(specs), 3)
        self.assertEqual(specs[0], {"role": "tank", "name": "Страж", "emoji": "🐻"})

    def test_grouped_format_and_russian_roles(self) -> None:
        payload = {
            "танк": [{"name": "Страж", "emoji": "🐻"}],
            "хил": [{"name": "Жрец", "emoji": "✨"}],
            "дд": [{"name": "Маг", "emoji": "🔮"}, {"name": "Воин", "emoji": "⚔️"}],
        }
        specs = parse_specs_payload(payload)
        self.assertEqual(len(specs), 4)
        self.assertEqual({spec["role"] for spec in specs}, {"tank", "heal", "dd"})

    def test_duplicates_are_merged(self) -> None:
        payload = [
            {"role": "tank", "name": "Страж", "emoji": "🐻"},
            {"role": "tank", "name": "страж", "emoji": "🛡️"},
        ]
        specs = parse_specs_payload(payload)
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0]["emoji"], "🛡️")

    def test_more_than_25_specs_for_one_role_is_rejected(self) -> None:
        payload = [
            {"role": "dd", "name": f"Специализация {i}", "emoji": "⚔️"}
            for i in range(26)
        ]
        with self.assertRaises(SpecImportError):
            parse_specs_payload(payload)

    def test_custom_emoji_validation(self) -> None:
        valid = "<:guard:123456789012345678>"
        self.assertEqual(normalize_emoji(valid), valid)
        self.assertIsNotNone(to_partial_emoji(valid))
        with self.assertRaises(SpecImportError):
            normalize_emoji("<:broken>")
        with self.assertRaises(SpecImportError):
            normalize_emoji("")

    def test_invalid_role_and_missing_icon_are_rejected(self) -> None:
        with self.assertRaises(SpecImportError):
            parse_specs_payload([{"role": "support", "name": "Тест", "emoji": "✨"}])
        with self.assertRaises(SpecImportError):
            parse_specs_payload([{"role": "heal", "name": "Тест"}])
        with self.assertRaises(SpecImportError):
            parse_specs_payload({"heal": "not-a-list"})


if __name__ == "__main__":
    unittest.main()
