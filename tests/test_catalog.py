from __future__ import annotations

import unittest
from pathlib import Path

from raidbot.catalog import CATALOG_PATH, bundled_catalog

SPEC_ICON_DIR = Path(__file__).resolve().parent.parent / "assets" / "spec_icons"


class CatalogTests(unittest.TestCase):
    def test_catalog_is_valid_and_complete(self) -> None:
        self.assertTrue(CATALOG_PATH.is_file())
        _, specs = bundled_catalog()

        self.assertEqual(len(specs), 11)
        counts = {"tank": 0, "heal": 0, "dd": 0}
        for spec in specs:
            counts[spec["role"]] += 1
            self.assertLessEqual(len(spec["name"]), 100)
            self.assertTrue((SPEC_ICON_DIR / spec["icon_file"]).is_file(), spec)

        self.assertEqual(counts, {"tank": 1, "heal": 1, "dd": 9})

    def test_expected_specializations_are_present(self) -> None:
        _, specs = bundled_catalog()
        by_id = {spec["id"]: spec for spec in specs}

        self.assertEqual(by_id["dryness"]["role"], "dd")
        self.assertEqual(by_id["power"]["role"], "tank")
        self.assertEqual(by_id["rain"]["role"], "heal")
        self.assertIn("Воздушный змей", by_id["sky-snake"]["name"])
        self.assertIn("Крылья", by_id["wing"]["name"])
        self.assertNotIn("bolt", by_id)


if __name__ == "__main__":
    unittest.main()
