from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from raidbot.assets import sync_role_icons, sync_spec_icons
from raidbot.store import Store


class FakeEmoji:
    _next_id = 100_000_000_000_000_000

    def __init__(self, name: str) -> None:
        FakeEmoji._next_id += 1
        self.id = FakeEmoji._next_id
        self.name = name
        self.animated = False


class FakePermissions:
    def __init__(self, can_manage: bool) -> None:
        self.manage_expressions = can_manage


class FakeGuild:
    def __init__(self, can_manage: bool = True) -> None:
        self.id = 42
        self.me = SimpleNamespace(guild_permissions=FakePermissions(can_manage))
        self.emojis: list[FakeEmoji] = []
        self.uploads: list[str] = []

    async def fetch_emojis(self) -> list[FakeEmoji]:
        return list(self.emojis)

    async def create_custom_emoji(
        self, *, name: str, image: bytes, reason: str
    ) -> FakeEmoji:
        self.uploads.append(name)
        emoji = FakeEmoji(name)
        self.emojis.append(emoji)
        return emoji


class RoleIconAssetTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temporary_directory.name) / "store.json")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    async def test_uploads_three_role_icons_and_saves_tags(self) -> None:
        guild = FakeGuild()
        result = await sync_role_icons(guild, self.store)

        self.assertEqual(result.uploaded, 3)
        self.assertIsNone(result.error)
        self.assertEqual(
            sorted(guild.uploads), ["raid_dd", "raid_heal", "raid_tank"]
        )

        settings = self.store.settings_for(guild.id)
        self.assertEqual(settings["role_icons_source"], "assets")
        for role, tag in result.emojis.items():
            self.assertTrue(tag.startswith("<:"))
            self.assertEqual(settings["role_emojis"][role], tag)

    async def test_second_sync_reuses_emojis(self) -> None:
        guild = FakeGuild()
        await sync_role_icons(guild, self.store)
        result = await sync_role_icons(guild, self.store)

        self.assertEqual(result.uploaded, 0)
        self.assertFalse(result.updated)
        self.assertEqual(len(guild.uploads), 3)

    async def test_without_permission_returns_error(self) -> None:
        guild = FakeGuild(can_manage=False)
        result = await sync_role_icons(guild, self.store)

        self.assertEqual(result.uploaded, 0)
        self.assertIsNotNone(result.error)
        self.assertIn("Управлять выражениями", result.error or "")
        self.assertEqual(guild.uploads, [])

    async def test_manual_icons_are_not_overridden_without_force(self) -> None:
        guild = FakeGuild()
        self.store.set_role_emojis(
            guild.id,
            {"tank": "🛡️", "heal": "🌿", "dd": "⚔️"},
            source="manual",
        )

        result = await sync_role_icons(guild, self.store)
        self.assertEqual(result.uploaded, 0)
        self.assertEqual(guild.uploads, [])

        forced = await sync_role_icons(guild, self.store, force=True)
        self.assertEqual(forced.uploaded, 3)
        self.assertEqual(
            self.store.settings_for(guild.id)["role_icons_source"], "assets"
        )


class SpecIconAssetTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temporary_directory.name) / "store.json")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    async def test_uploads_catalog_spec_icons(self) -> None:
        guild = FakeGuild()
        result = await sync_spec_icons(guild, self.store)

        self.assertEqual(result.uploaded, 12)
        self.assertIsNone(result.error)
        self.assertIn("raid_spec_dryness", guild.uploads)
        self.assertIn("raid_spec_sky_snake", guild.uploads)
        self.assertIn("raid_spec_strenght", guild.uploads)
        self.assertIn("raid_spec_wing", guild.uploads)
        self.assertIn("raid_spec_bolt", guild.uploads)

        settings = self.store.settings_for(guild.id)
        self.assertTrue(all(str(spec["emoji"]).startswith("<") for spec in settings["specs"]))
        self.assertTrue(all(spec.get("icon_file") for spec in settings["specs"]))

    async def test_second_spec_sync_does_not_upload_again(self) -> None:
        guild = FakeGuild()
        await sync_spec_icons(guild, self.store)
        uploads_before = len(guild.uploads)
        result = await sync_spec_icons(guild, self.store)

        self.assertEqual(result.uploaded, 0)
        self.assertFalse(result.updated)
        self.assertEqual(len(guild.uploads), uploads_before)

    async def test_spec_upload_without_permission_reports_error(self) -> None:
        guild = FakeGuild(can_manage=False)
        result = await sync_spec_icons(guild, self.store)

        self.assertEqual(result.uploaded, 0)
        self.assertIn("Управлять выражениями", result.error or "")
        self.assertEqual(guild.uploads, [])


if __name__ == "__main__":
    unittest.main()
