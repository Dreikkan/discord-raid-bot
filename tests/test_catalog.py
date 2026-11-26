from __future__ import annotations

import unittest

from raidbot.catalog import CATALOG_PATH, bundled_catalog
from raidbot.constants import DEFAULT_ROLE_EMOJIS


class CatalogTests(unittest.TestCase):
    def test_catalog_is_static_and_complete(self) -> None:
        self.assertTrue(CATALOG_PATH.is_file())
        specs = bundled_catalog()

        self.assertEqual(len(specs), 12)
        counts = {"tank": 0, "heal": 0, "dd": 0}
        for spec in specs:
            counts[spec["role"]] += 1
            self.assertLessEqual(len(spec["name"]), 100)
            self.assertRegex(spec["emoji"], r"^<:[A-Za-z0-9_]+:[0-9]{15,22}>$")

        self.assertEqual(counts, {"tank": 1, "heal": 1, "dd": 10})

    def test_expected_specializations_and_emojis(self) -> None:
        specs = bundled_catalog()
        by_id = {spec["id"]: spec for spec in specs}
        expected_emojis = {
            "power": "<:power:1575602126569349180>",
            "rain": "<:rain:1575602128217710736>",
            "dryness": "<:dryness:1575602116746289222>",
            "dust": "<:dust:1575602118696374483>",
            "nameless": "<:nameless:1575602122442023142>",
            "nefrit": "<:nefrit:1575602124480454858>",
            "sky-snake": "<:skysneak:1575602130352472125>",
            "strateg": "<:strateg:1575602132336386260>",
            "strenght": "<:strenght:1575602135041581096>",
            "wind": "<:wind:1575602139152261341>",
            "wing": "<:wings:1575602141454663740>",
            "bolt": "<:bolt:1575608158519296131>",
        }

        self.assertEqual(set(by_id), set(expected_emojis))
        for spec_id, expected_emoji in expected_emojis.items():
            self.assertEqual(by_id[spec_id]["emoji"], expected_emoji)
        self.assertEqual(by_id["power"]["role"], "tank")
        self.assertEqual(by_id["rain"]["role"], "heal")
        self.assertEqual(by_id["bolt"]["role"], "dd")
        self.assertIn("Перчатки небесной воли", by_id["sky-snake"]["name"])
        self.assertIn("Поясной барабан муз", by_id["wing"]["name"])

    def test_role_emojis_are_static_application_emojis(self) -> None:
        expected = {
            "tank": "<:tank:1575602137033875720>",
            "heal": "<:heal:1575602120672022588>",
            "dd": "<:DD:1575602114674032793>",
        }
        self.assertEqual(DEFAULT_ROLE_EMOJIS, expected)


if __name__ == "__main__":
    unittest.main()
