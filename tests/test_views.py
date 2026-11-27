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
        self.assertEqual(view.children[0].label, "Участвовать")
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

    async def test_tank_goes_to_bench_when_tank_is_taken(self) -> None:
        self.store.set_limits(self.guild_id, {"tank": 0, "heal": 3, "dd": 8})
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
        registration = saved["registrations"]["777"]
        self.assertEqual(registration["status"], STATUS_BENCH)
        self.assertTrue(registration["waiting_for_tank_slot"])
        interaction.response.defer.assert_awaited_once()
        interaction.edit_original_response.assert_awaited_once()
        done_embed = interaction.edit_original_response.await_args.kwargs["embed"]
        self.assertIn("автоматически", done_embed.description)

    async def test_status_join_stays_main_when_space_is_available(self) -> None:
        spec = self.store.specs_for_role(self.guild_id, "tank")[0]
        view = StatusView(self.bot, self.raid["id"], 777, "tank", [spec])
        interaction = FakeInteraction()

        with patch("raidbot.views.refresh_raid_panel", new=AsyncMock(return_value=True)):
            await view._set_status(interaction, status=STATUS_MAIN)

        saved = self.store.get_raid(self.raid["id"])
        assert saved is not None
        registration = saved["registrations"]["777"]
        self.assertEqual(registration["role"], "tank")
        self.assertEqual(registration["status"], STATUS_MAIN)
        self.assertFalse(registration["waiting_for_tank_slot"])

    async def test_tank_waits_when_dd_is_eight_of_eight(self) -> None:
        for user_id in range(1, 9):
            self.store.set_registration(
                self.raid["id"],
                user_id,
                role="dd",
                specializations=[],
                display_name=f"DD {user_id}",
                status=STATUS_MAIN,
            )
        spec = self.store.specs_for_role(self.guild_id, "tank")[0]
        view = StatusView(self.bot, self.raid["id"], 777, "tank", [spec])
        interaction = FakeInteraction()

        with patch("raidbot.views.refresh_raid_panel", new=AsyncMock(return_value=True)):
            await view._set_status(interaction, status=STATUS_MAIN)

        saved = self.store.get_raid(self.raid["id"])
        assert saved is not None
        registration = saved["registrations"]["777"]
        self.assertEqual(registration["role"], "tank")
        self.assertEqual(registration["status"], STATUS_BENCH)
        self.assertTrue(registration["waiting_for_tank_slot"])

    async def test_waiting_tank_is_promoted_when_dd_frees_slot(self) -> None:
        for user_id in range(1, 9):
            self.store.set_registration(
                self.raid["id"],
                user_id,
                role="dd",
                specializations=[],
                display_name=f"DD {user_id}",
                status=STATUS_MAIN,
            )
        tank_spec = self.store.specs_for_role(self.guild_id, "tank")[0]
        self.store.set_registration(
            self.raid["id"],
            100,
            role="tank",
            specializations=[tank_spec],
            display_name="Танк",
            status=STATUS_BENCH,
            waiting_for_tank_slot=True,
        )
        self.store.set_registration(
            self.raid["id"],
            1,
            role="dd",
            specializations=[],
            display_name="DD 1",
            status=STATUS_BENCH,
        )

        saved = self.store.get_raid(self.raid["id"])
        assert saved is not None
        self.assertEqual(
            saved["registrations"]["100"]["status"], STATUS_MAIN
        )
        self.assertFalse(
            saved["registrations"]["100"]["waiting_for_tank_slot"]
        )

    async def test_main_tank_switching_to_bench_keeps_waiting_tank_benched(
        self,
    ) -> None:
        tank_spec = self.store.specs_for_role(self.guild_id, "tank")[0]
        self.store.set_registration(
            self.raid["id"],
            100,
            role="tank",
            specializations=[tank_spec],
            display_name="Танк",
            status=STATUS_MAIN,
        )
        for user_id in range(1, 8):
            self.store.set_registration(
                self.raid["id"],
                user_id,
                role="dd",
                specializations=[],
                display_name=f"DD {user_id}",
                status=STATUS_MAIN,
            )
        self.store.set_registration(
            self.raid["id"],
            200,
            role="tank",
            specializations=[tank_spec],
            display_name="Ожидающий",
            status=STATUS_BENCH,
            waiting_for_tank_slot=True,
        )

        view = StatusView(
            self.bot, self.raid["id"], 100, "tank", [tank_spec]
        )
        interaction = FakeInteraction()

        with patch(
            "raidbot.views.refresh_raid_panel", new=AsyncMock(return_value=True)
        ):
            await view._set_status(interaction, status=STATUS_BENCH)

        saved = self.store.get_raid(self.raid["id"])
        assert saved is not None
        self.assertEqual(
            saved["registrations"]["100"]["status"], STATUS_BENCH
        )
        self.assertEqual(
            saved["registrations"]["200"]["status"], STATUS_BENCH
        )
        self.assertTrue(
            saved["registrations"]["200"]["waiting_for_tank_slot"]
        )

    async def test_dd_switching_to_bench_promotes_waiting_tank(self) -> None:
        dd_spec = self.store.specs_for_role(self.guild_id, "dd")[0]
        tank_spec = self.store.specs_for_role(self.guild_id, "tank")[0]
        for user_id in range(1, 9):
            self.store.set_registration(
                self.raid["id"],
                user_id,
                role="dd",
                specializations=[dd_spec],
                display_name=f"DD {user_id}",
                status=STATUS_MAIN,
            )
        self.store.set_registration(
            self.raid["id"],
            200,
            role="tank",
            specializations=[tank_spec],
            display_name="Ожидающий",
            status=STATUS_BENCH,
            waiting_for_tank_slot=True,
        )

        view = StatusView(self.bot, self.raid["id"], 1, "dd", [dd_spec])
        interaction = FakeInteraction()

        with patch(
            "raidbot.views.refresh_raid_panel", new=AsyncMock(return_value=True)
        ):
            await view._set_status(interaction, status=STATUS_BENCH)

        saved = self.store.get_raid(self.raid["id"])
        assert saved is not None
        self.assertEqual(saved["registrations"]["1"]["status"], STATUS_BENCH)
        self.assertEqual(
            saved["registrations"]["200"]["status"], STATUS_MAIN
        )
        self.assertFalse(
            saved["registrations"]["200"]["waiting_for_tank_slot"]
        )

    async def test_dd_can_choose_single_specialization(self) -> None:
        view = SpecSelectView(self.bot, self.raid["id"], 777, "dd")
        selected_id = view.children[0].options[0].value
        interaction = FakeInteraction({"values": [selected_id]})

        await view._on_spec(interaction)

        new_view = interaction.response.edit_message.await_args.kwargs["view"]
        self.assertIsInstance(new_view, StatusView)
        self.assertEqual(len(new_view.specs), 1)
        self.assertEqual(new_view.specs[0]["id"], selected_id)

    async def test_dd_role_offers_tank_specialization(self) -> None:
        tank_spec = self.store.specs_for_role(self.guild_id, "tank")[0]
        view = SpecSelectView(self.bot, self.raid["id"], 777, "dd")
        values = [option.value for option in view.children[0].options]
        self.assertIn(tank_spec["id"], values)

        interaction = FakeInteraction({"values": [tank_spec["id"]]})
        await view._on_spec(interaction)

        new_view = interaction.response.edit_message.await_args.kwargs["view"]
        self.assertIsInstance(new_view, StatusView)
        self.assertEqual(new_view.role, "dd")
        self.assertEqual(new_view.specs[0]["id"], tank_spec["id"])

        status_interaction = FakeInteraction()
        with patch(
            "raidbot.views.refresh_raid_panel", new=AsyncMock(return_value=True)
        ):
            await new_view._set_status(
                status_interaction, status=STATUS_MAIN
            )

        saved = self.store.get_raid(self.raid["id"])
        assert saved is not None
        registration = saved["registrations"]["777"]
        self.assertEqual(registration["role"], "dd")
        self.assertEqual(registration["status"], STATUS_MAIN)
        self.assertEqual(
            registration["specializations"][0]["id"], tank_spec["id"]
        )

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
        with patch("raidbot.views.refresh_raid_panel", new=AsyncMock(return_value=True)) as refresh_mock:
            await panel._start_registration(first_interaction)
        refresh_mock.assert_awaited_once()

        self.assertIsNone(
            self.store.get_raid(self.raid["id"])["registrations"].get("777")
        )
        role_view = first_interaction.response.send_message.await_args.kwargs["view"]
        self.assertIsInstance(role_view, RoleSelectView)

        raid = self.store.get_raid(self.raid["id"])
        assert raid is not None
        role_text = role_view.build_embed(raid).description or ""
        self.assertNotIn("Текущая запись:", role_text)
        self.assertIn("Старая запись удалена", role_text)
        self.assertFalse(any(option.default for option in role_view.children[0].options))

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
        with patch("raidbot.views.refresh_raid_panel", new=AsyncMock(return_value=True)):
            await done_view.children[0].callback(edit_interaction)
        reopened = edit_interaction.response.edit_message.await_args.kwargs["view"]
        self.assertIsInstance(reopened, RoleSelectView)

        saved = self.store.get_raid(self.raid["id"])
        assert saved is not None
        self.assertNotIn("777", saved["registrations"])


if __name__ == "__main__":
    unittest.main()
