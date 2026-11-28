from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from raidbot.settings_panel import (
    ActivityChannelView,
    ActivityRoleView,
    ActivitySettingsView,
    AddActivityModal,
    GeneralSettingsModal,
    SettingsView,
    WelcomeSettingsView,
    WelcomeTextModal,
)
from raidbot.store import Store


class FakeBot:
    def __init__(self, store: Store) -> None:
        self.store = store

    def get_guild(self, guild_id: int):
        return None


class SettingsPanelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temporary_directory.name) / "store.json")
        self.bot = FakeBot(self.store)
        self.settings = self.store.settings_for(1)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_main_panel_shows_all_settings(self) -> None:
        self.settings["title"] = "Тестовый рейд"
        self.settings["limits"] = {"tank": 1, "heal": 2, "dd": 7}
        self.settings["timezone"] = "Europe/Moscow"
        activity = self.settings["activities"][0]
        activity["channel_id"] = 10
        activity["role_id"] = 20
        activity["description"] = "Описание активности"
        self.store.save_activity(1, activity)
        self.store.save()

        view = SettingsView(self.bot, 1)
        embed = view.build_embed()
        fields = {field.name: field.value for field in embed.fields}

        self.assertEqual(embed.title, "Настройки")
        self.assertIn("Рейд", fields)
        self.assertIn("Тестовый рейд", fields["Рейд"])
        self.assertIn("Танк: 1", fields["Рейд"])
        self.assertIn("Хил: 2", fields["Рейд"])
        self.assertIn("ДД: 7", fields["Рейд"])
        self.assertIn("Europe/Moscow", fields["Рейд"])

        self.assertIn("Приветствие новых участников", fields)
        self.assertIn("не настроено", fields["Приветствие новых участников"])

        self.assertIn("Вечеринка", fields)
        self.assertIn("Ежедневно, 21:00–21:30", fields["Вечеринка"])
        self.assertIn("<#10>", fields["Вечеринка"])
        self.assertIn("<@&20>", fields["Вечеринка"])
        self.assertIn("Описание активности", fields["Вечеринка"])
        self.assertIn("Автоудаление", fields["Вечеринка"])

        select = next(
            item for item in view.children if isinstance(item, discord.ui.Select)
        )
        self.assertEqual(len(select.options), len(self.settings["activities"]))
        labels = [item.label for item in view.children if hasattr(item, "label")]
        self.assertIn("Настройки рейда", labels)
        self.assertIn("Приветствие", labels)
        self.assertIn("Добавить активность", labels)

    def test_activity_detail_and_pickers(self) -> None:
        activity = self.settings["activities"][0]
        view = ActivitySettingsView(self.bot, 1, activity["id"])
        embed = view.build_embed()

        self.assertEqual(embed.title, "Вечеринка")
        labels = [item.label for item in view.children if hasattr(item, "label")]
        self.assertEqual(
            labels,
            ["Описание", "Расписание", "Канал", "Роль", "Автоудаление", "Назад"],
        )

        channel_view = ActivityChannelView(self.bot, 1, activity["id"])
        self.assertIn("Канал", channel_view.build_embed().title)
        role_view = ActivityRoleView(self.bot, 1, activity["id"])
        self.assertIn("Роль", role_view.build_embed().title)

    def test_welcome_settings_view_and_text_modal(self) -> None:
        view = WelcomeSettingsView(self.bot, 1)
        labels = [item.label for item in view.children if hasattr(item, "label")]
        self.assertEqual(
            labels,
            ["Включить", "Канал", "Текст", "Предпросмотр", "Назад"],
        )
        embed = view.build_embed()
        self.assertIn("Приветствие", embed.title)
        self.assertIn("Не настроено", embed.description)
        self.assertIn("{user}", embed.description)

        modal = WelcomeTextModal(self.bot, 1, view)
        self.assertEqual(
            [item.label for item in modal.children],
            ["Заголовок", "Сообщение"],
        )
        self.assertTrue(modal.title_input.default)
        self.assertTrue(modal.message_input.default)

    def test_modals_are_created_with_current_values(self) -> None:
        panel = SettingsView(self.bot, 1)
        general = GeneralSettingsModal(self.bot, 1, panel)
        self.assertEqual(
            [item.label for item in general.children],
            ["Название рейда", "Танки", "Хилы", "ДД", "Часовой пояс"],
        )
        self.assertEqual(general.tank_input.default, "0")
        self.assertEqual(general.heal_input.default, "2")
        self.assertEqual(general.dd_input.default, "8")
        self.assertEqual(general.timezone_input.default, "Europe/Moscow")

        add = AddActivityModal(self.bot, 1, panel)
        self.assertEqual(
            [item.label for item in add.children],
            ["Название", "Расписание", "Описание"],
        )


class SettingsPanelInteractionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temporary_directory.name) / "store.json")
        self.bot = FakeBot(self.store)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    async def test_general_settings_modal_saves_values(self) -> None:
        parent = SettingsView(self.bot, 1)
        parent.message = SimpleNamespace(id=1)
        modal = GeneralSettingsModal(self.bot, 1, parent)
        modal.title_input._value = "Новое название"
        modal.tank_input._value = "2"
        modal.heal_input._value = "4"
        modal.dd_input._value = "9"
        modal.timezone_input._value = "UTC+5"

        response = SimpleNamespace(
            edit_message=AsyncMock(),
            send_message=AsyncMock(),
        )
        interaction = SimpleNamespace(
            message=SimpleNamespace(id=1),
            response=response,
        )

        await modal.on_submit(interaction)

        settings = self.store.settings_for(1)
        self.assertEqual(settings["title"], "Новое название")
        self.assertEqual(settings["limits"], {"tank": 2, "heal": 4, "dd": 9})
        self.assertEqual(settings["timezone"], "UTC+05:00")
        response.edit_message.assert_awaited_once()

    async def test_welcome_text_modal_saves_values(self) -> None:
        parent = WelcomeSettingsView(self.bot, 1)
        parent.message = SimpleNamespace(id=1)
        modal = WelcomeTextModal(self.bot, 1, parent)
        modal.title_input._value = "Новое приветствие"
        modal.message_input._value = "Привет, {user}!"

        response = SimpleNamespace(
            edit_message=AsyncMock(),
            send_message=AsyncMock(),
        )
        interaction = SimpleNamespace(
            message=SimpleNamespace(id=1),
            response=response,
        )

        await modal.on_submit(interaction)

        welcome = self.store.settings_for(1)["welcome"]
        self.assertEqual(welcome["title"], "Новое приветствие")
        self.assertEqual(welcome["message"], "Привет, {user}!")
        response.edit_message.assert_awaited_once()

    async def test_welcome_preview_is_ephemeral(self) -> None:
        view = WelcomeSettingsView(self.bot, 1)
        view.message = SimpleNamespace(id=1)
        guild = SimpleNamespace(
            name="Сервер", member_count=10, icon=None
        )
        member = SimpleNamespace(
            id=5,
            display_name="Админ",
            display_avatar=None,
            joined_at=None,
        )
        response = SimpleNamespace(
            send_message=AsyncMock(),
            edit_message=AsyncMock(),
        )
        interaction = SimpleNamespace(
            guild=guild,
            user=member,
            response=response,
        )

        await view._preview(interaction)

        response.send_message.assert_awaited_once()
        kwargs = response.send_message.await_args.kwargs
        self.assertTrue(kwargs["ephemeral"])
        self.assertIn("Предпросмотр", kwargs["content"])
        self.assertIn("<@5>", kwargs["embed"].description or "")


if __name__ == "__main__":
    unittest.main()
