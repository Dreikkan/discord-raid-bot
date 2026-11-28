from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from raidbot.store import Store
from raidbot.welcome import (
    DEFAULT_WELCOME_MESSAGE,
    DEFAULT_WELCOME_TITLE,
    WELCOME_COLOR,
    build_welcome_embed,
    normalize_welcome,
    render_welcome_text,
    send_welcome,
)


class WelcomeEmbedTests(unittest.TestCase):
    def test_defaults_and_normalization(self) -> None:
        welcome = normalize_welcome(None)
        self.assertFalse(welcome["enabled"])
        self.assertIsNone(welcome["channel_id"])
        self.assertEqual(welcome["title"], DEFAULT_WELCOME_TITLE)
        self.assertEqual(welcome["message"], DEFAULT_WELCOME_MESSAGE)

        enabled_without_channel = normalize_welcome({"enabled": True})
        self.assertFalse(enabled_without_channel["enabled"])

        sanitized = normalize_welcome(
            {
                "enabled": True,
                "channel_id": "42",
                "title": "  Заголовок  ",
                "message": "  Текст  ",
            }
        )
        self.assertTrue(sanitized["enabled"])
        self.assertEqual(sanitized["channel_id"], 42)
        self.assertEqual(sanitized["title"], "Заголовок")
        self.assertEqual(sanitized["message"], "Текст")

    def test_old_default_message_is_migrated_without_member_count(self) -> None:
        old_default = (
            "Привет, {user}! Рады видеть тебя на **{server}**.\n"
            "Ты — **{count}**-й участник. "
            "Желаем отличного времени и удачных рейдов!"
        )
        welcome = normalize_welcome({"message": old_default})
        self.assertEqual(welcome["message"], DEFAULT_WELCOME_MESSAGE)
        self.assertNotIn("{count}", welcome["message"])

    def test_placeholders_are_rendered_and_markdown_is_escaped(self) -> None:
        text = render_welcome_text(
            "{user} · {username} · {server}",
            member_id=42,
            username="Новый_игрок",
            guild_name="Мой*сервер",
        )
        self.assertEqual(
            text, "<@42> · Новый\\_игрок · Мой\\*сервер"
        )

        count_text = render_welcome_text(
            "{count}",
            member_id=42,
            username="Игрок",
            guild_name="Сервер",
            member_count=7,
        )
        self.assertEqual(count_text, "7")

    def test_embed_uses_avatar_and_guild_branding(self) -> None:
        guild = SimpleNamespace(
            name="Рейдовый сервер",
            member_count=128,
            icon=SimpleNamespace(url="https://cdn.example/icon.png"),
        )
        member = SimpleNamespace(
            id=42,
            display_name="Новый игрок",
            display_avatar=SimpleNamespace(
                url="https://cdn.example/avatar.png"
            ),
            joined_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        welcome = {
            "title": "Добро пожаловать!",
            "message": "Привет, {user}! Ты на {server}.",
        }

        embed = build_welcome_embed(guild, member, welcome)

        self.assertEqual(embed.title, "Добро пожаловать!")
        self.assertIn("<@42>", embed.description or "")
        self.assertIn("Рейдовый сервер", embed.description or "")
        self.assertEqual(embed.author.name, "Рейдовый сервер")
        self.assertEqual(
            embed.author.icon_url, "https://cdn.example/icon.png"
        )
        self.assertEqual(
            embed.thumbnail.url, "https://cdn.example/avatar.png"
        )
        self.assertEqual(embed.fields, [])
        self.assertEqual(
            embed.footer.text, "Рейдовый сервер · Новый участник"
        )
        self.assertEqual(embed.color.value, WELCOME_COLOR)


class WelcomeSendTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_welcome_to_configured_channel(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary) / "store.json")
            store.save_welcome(
                1,
                {
                    "enabled": True,
                    "channel_id": 10,
                    "title": "Привет!",
                    "message": "Привет, {user}!",
                },
            )
            channel = SimpleNamespace(send=AsyncMock())
            guild = SimpleNamespace(
                id=1,
                name="Сервер",
                member_count=5,
                icon=None,
                me=None,
                get_channel=lambda channel_id: channel,
            )
            member = SimpleNamespace(
                id=42,
                guild=guild,
                display_name="Игрок",
                display_avatar=None,
                joined_at=None,
            )

            sent = await send_welcome(store, member)

            self.assertTrue(sent)
            channel.send.assert_awaited_once()
            embed = channel.send.await_args.kwargs["embed"]
            self.assertEqual(embed.title, "Привет!")
            self.assertIn("<@42>", embed.description or "")
            mentions = channel.send.await_args.kwargs["allowed_mentions"]
            self.assertTrue(mentions.users)
            self.assertFalse(mentions.everyone)
            self.assertFalse(mentions.roles)

    async def test_bots_are_not_welcomed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary) / "store.json")
            store.save_welcome(1, {"enabled": True, "channel_id": 10})
            channel = SimpleNamespace(send=AsyncMock())
            guild = SimpleNamespace(
                id=1,
                name="Сервер",
                member_count=5,
                icon=None,
                me=None,
                get_channel=lambda channel_id: channel,
            )
            member = SimpleNamespace(
                id=42,
                bot=True,
                guild=guild,
                display_name="Бот",
                display_avatar=None,
                joined_at=None,
            )

            self.assertFalse(await send_welcome(store, member))
            channel.send.assert_not_awaited()

    async def test_skips_disabled_or_missing_channel(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary) / "store.json")
            channel = SimpleNamespace(send=AsyncMock())
            guild = SimpleNamespace(
                id=1,
                name="Сервер",
                member_count=5,
                icon=None,
                me=None,
                get_channel=lambda channel_id: channel,
            )
            member = SimpleNamespace(
                id=42,
                guild=guild,
                display_name="Игрок",
                display_avatar=None,
                joined_at=None,
            )

            self.assertFalse(await send_welcome(store, member))

            store.save_welcome(
                1, {"enabled": True, "channel_id": 10}
            )
            guild.get_channel = lambda channel_id: None
            self.assertFalse(await send_welcome(store, member))
            channel.send.assert_not_awaited()

    async def test_skips_channel_without_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary) / "store.json")
            store.save_welcome(
                1, {"enabled": True, "channel_id": 10}
            )
            channel = SimpleNamespace(
                send=AsyncMock(),
                permissions_for=lambda member: SimpleNamespace(
                    send_messages=False, embed_links=True
                ),
            )
            guild = SimpleNamespace(
                id=1,
                name="Сервер",
                member_count=5,
                icon=None,
                me=SimpleNamespace(id=999),
                get_channel=lambda channel_id: channel,
            )
            member = SimpleNamespace(
                id=42,
                guild=guild,
                display_name="Игрок",
                display_avatar=None,
                joined_at=None,
            )

            self.assertFalse(await send_welcome(store, member))
            channel.send.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
