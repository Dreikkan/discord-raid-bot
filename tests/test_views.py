from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from raidbot.constants import STATUS_BENCH, STATUS_MAIN
from raidbot.store import Store
from raidbot.views import (
    RaidPanelView,
    RegistrationDoneView,
    RoleSelectView,
    SpecSelectView,
    StatusView,
)


class FakeResponse:
    def __init__(self) -> None:
        self.send_message = AsyncMock()
        self.edit_message = AsyncMock()
        self.defer = AsyncMock()

    def is_done(self) -> bool:
        return False


class FakeUser:
    id = 777
    name = "Tester"
    display_name = "Тестовый игрок"


class FakeInteraction:
    def __init__(self, data: dict | None = None) -> None:
        self.data = data or {}
        self.user = FakeUser()
        self.response = FakeResponse()
        self.original_response = AsyncMock(return_value=SimpleNamespace(id=1))
        self.edit_original_response = AsyncMock()


class FakeBot:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.add_view = lambda *args, **kwargs: None


class ViewFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        path = Path(self.temporary_directory.name) / "store.json"
        self.store = Store(path)
        self.bot = FakeBot(self.store)
        self.guild_id = 1

        settings = self.store.settings_for(self.guild_id)
        self.raid = self.store.create_raid(
            guild_id=self.guild_id,
            channel_id=2,
            created_by=3,
            title=settings["title"],
            description="Тестовый рейд",
            start_at=2_000_000_000,
            limits=settings["limits"],
            role_emojis=settings["role_emojis"],
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    async def test_public_button_opens_ephemeral_role_page(self) -> None:
        view = RaidPanelView(self.bot, self.raid["id"])
        interaction = FakeInteraction()
        await view._start_registration(interaction)

        interaction.response.send_message.assert_awaited_once()
        sent_view = interaction.response.send_message.await_args.kwargs["view"]
        self.assertIsInstance(sent_view, RoleSelectView)
        self.assertTrue(interaction.response.send_message.await_args.kwargs["ephemeral"])

    async def test_role_selection_opens_specialization_page(self) -> None:
        view = RoleSelectView(self.bot, self.raid["id"], 777)
        view.message = SimpleNamespace(id=1)
        interaction = FakeInteraction({"values": ["tank"]})

        await view._on_role(interaction)

        interaction.response.edit_message.assert_awaited_once()
        new_view = interaction.response.edit_message.await_args.kwargs["view"]
        self.assertEqual(new_view.role, "tank")
        self.assertEqual(new_view.build_embed(self.raid).title, "Регистрация на рейд")

    async def test_status_join_redirects_to_bench_when_full(self) -> None:
        self.store.set_limits(self.guild_id, {"tank": 1, "heal": 3, "dd": 8})
        self.raid = self.store.get_raid(self.raid["id"])
        assert self.raid is not None
        self.raid["limits"]["tank"] = 1
        self.store.save()
        self.store.set_registration(
            self.raid["id"],
            100,
            role="tank",
            specializations=[
                {"id": "one", "name": "Страж", "emoji": "🐻"}
            ],
            display_name="Первый",
            status=STATUS_MAIN,
        )

        spec = self.store.specs_for_role(self.guild_id, "tank")[0]
        view = StatusView(self.bot, self.raid["id"], 777, "tank", [spec])
        interaction = FakeInteraction()

        with patch("raidbot.views.refresh_raid_panel", new=AsyncMock(return_value=True)):
            await view._set_status(interaction, status=STATUS_MAIN)

        saved = self.store.get_raid(self.raid["id"])
        assert saved is not None
        self.assertEqual(saved["registrations"]["777"]["status"], STATUS_BENCH)
        interaction.response.defer.assert_awaited_once()
        interaction.edit_original_response.assert_awaited_once()
        done_embed = interaction.edit_original_response.await_args.kwargs["embed"]
        self.assertIn("скамью запасных", done_embed.description)

    async def test_status_join_stays_main_when_space_is_available(self) -> None:
        spec = self.store.specs_for_role(self.guild_id, "tank")[0]
        view = StatusView(self.bot, self.raid["id"], 777, "tank", [spec])
        interaction = FakeInteraction()

        with patch("raidbot.views.refresh_raid_panel", new=AsyncMock(return_value=True)):
            await view._set_status(interaction, status=STATUS_MAIN)

        saved = self.store.get_raid(self.raid["id"])
        assert saved is not None
        self.assertEqual(saved["registrations"]["777"]["status"], STATUS_MAIN)

    async def test_dd_can_choose_single_specialization(self) -> None:
        view = SpecSelectView(self.bot, self.raid["id"], 777, "dd")
        selected_id = view.children[0].options[0].value
        interaction = FakeInteraction({"values": [selected_id]})

        await view._on_spec(interaction)

        new_view = interaction.response.edit_message.await_args.kwargs["view"]
        self.assertIsInstance(new_view, StatusView)
        self.assertEqual(len(new_view.specs), 1)
        self.assertEqual(new_view.specs[0]["id"], selected_id)

    async def test_existing_registration_can_be_changed_from_scratch(self) -> None:
        initial_spec = self.store.specs_for_role(self.guild_id, "tank")[0]
        self.store.set_registration(
            self.raid["id"],
            777,
            role="tank",
            specializations=[initial_spec],
            display_name="Старое имя",
            status=STATUS_MAIN,
        )

        panel = RaidPanelView(self.bot, self.raid["id"])
        first_interaction = FakeInteraction()
        await panel._start_registration(first_interaction)
        role_view = first_interaction.response.send_message.await_args.kwargs["view"]
        self.assertIsInstance(role_view, RoleSelectView)

        raid = self.store.get_raid(self.raid["id"])
        assert raid is not None
        role_text = role_view.build_embed(raid).description or ""
        self.assertIn("Текущая запись:", role_text)
        self.assertIn("текущая запись заменится", role_text)

        role_view.message = SimpleNamespace(id=1)
        role_interaction = FakeInteraction({"values": ["dd"]})
        await role_view._on_role(role_interaction)
        spec_view = role_interaction.response.edit_message.await_args.kwargs["view"]
        self.assertIsInstance(spec_view, SpecSelectView)
        self.assertEqual(spec_view.role, "dd")
        self.assertEqual(spec_view.children[0].max_values, 2)
        self.assertEqual(spec_view.children[0].min_values, 1)

        new_spec_ids = [
            spec_view.children[0].options[0].value,
            spec_view.children[0].options[1].value,
        ]
        spec_view.message = SimpleNamespace(id=1)
        spec_interaction = FakeInteraction({"values": new_spec_ids})
        await spec_view._on_spec(spec_interaction)
        status_view = spec_interaction.response.edit_message.await_args.kwargs["view"]
        self.assertIsInstance(status_view, StatusView)
        self.assertEqual(status_view.role, "dd")
        self.assertEqual(len(status_view.specs), 2)

        final_interaction = FakeInteraction()
        with patch("raidbot.views.refresh_raid_panel", new=AsyncMock(return_value=True)):
            await status_view._set_status(final_interaction, status=STATUS_BENCH)

        saved = self.store.get_raid(self.raid["id"])
        assert saved is not None
        registration = saved["registrations"]["777"]
        self.assertEqual(registration["role"], "dd")
        self.assertEqual(
            [spec["id"] for spec in registration["specializations"]],
            new_spec_ids,
        )
        self.assertEqual(registration["status"], STATUS_BENCH)
        self.assertEqual(registration["display_name"], "Тестовый игрок")

        done_view = final_interaction.edit_original_response.await_args.kwargs["view"]
        self.assertIsInstance(done_view, RegistrationDoneView)
        done_view.message = SimpleNamespace(id=1)

        edit_interaction = FakeInteraction()
        await done_view.children[0].callback(edit_interaction)
        reopened = edit_interaction.response.edit_message.await_args.kwargs["view"]
        self.assertIsInstance(reopened, RoleSelectView)


if __name__ == "__main__":
    unittest.main()
