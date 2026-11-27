from __future__ import annotations

import unittest
from types import SimpleNamespace

from raidbot.commands import settings_admin_check
from raidbot.constants import SETTINGS_ADMIN_ROLE_IDS


class SettingsAdminCheckTests(unittest.IsolatedAsyncioTestCase):
    async def test_listed_admin_role_is_allowed(self) -> None:
        interaction = SimpleNamespace(
            guild=SimpleNamespace(owner_id=1),
            user=SimpleNamespace(
                id=2,
                roles=[SimpleNamespace(id=SETTINGS_ADMIN_ROLE_IDS[0])],
            ),
        )
        self.assertTrue(await settings_admin_check(interaction))

    async def test_member_without_admin_role_is_denied(self) -> None:
        interaction = SimpleNamespace(
            guild=SimpleNamespace(owner_id=1),
            user=SimpleNamespace(
                id=2,
                roles=[SimpleNamespace(id=999)],
            ),
        )
        self.assertFalse(await settings_admin_check(interaction))

    async def test_server_owner_is_allowed(self) -> None:
        interaction = SimpleNamespace(
            guild=SimpleNamespace(owner_id=2),
            user=SimpleNamespace(id=2, roles=[]),
        )
        self.assertTrue(await settings_admin_check(interaction))

    async def test_direct_message_is_denied(self) -> None:
        interaction = SimpleNamespace(
            guild=None,
            user=SimpleNamespace(id=2, roles=[]),
        )
        self.assertFalse(await settings_admin_check(interaction))


if __name__ == "__main__":
    unittest.main()
