from __future__ import annotations

import logging
import re
from typing import Any

import discord

from .text import escape_markdown

log = logging.getLogger(__name__)

WELCOME_COLOR = 0x8B5CF6
DEFAULT_WELCOME_TITLE = "👋 Добро пожаловать!"
DEFAULT_WELCOME_MESSAGE = (
    "Привет, {user}! Рады видеть тебя на **{server}**.\n"
    "Желаем отличного времени и удачных рейдов!"
)
_OLD_DEFAULT_WELCOME_MESSAGE = (
    "Привет, {user}! Рады видеть тебя на **{server}**.\n"
    "Ты — **{count}**-й участник. Желаем отличного времени и удачных рейдов!"
)
MAX_WELCOME_TITLE_LENGTH = 200
MAX_WELCOME_MESSAGE_LENGTH = 1500

_PLACEHOLDER_RE = re.compile(r"\{(user|username|server|count)\}")


def default_welcome() -> dict[str, Any]:
    return {
        "enabled": False,
        "channel_id": None,
        "title": DEFAULT_WELCOME_TITLE,
        "message": DEFAULT_WELCOME_MESSAGE,
    }


def normalize_welcome(raw: Any) -> dict[str, Any]:
    welcome = default_welcome()
    if not isinstance(raw, dict):
        return welcome

    title = raw.get("title")
    if isinstance(title, str) and title.strip():
        welcome["title"] = title.strip()[:MAX_WELCOME_TITLE_LENGTH]

    message = raw.get("message")
    if isinstance(message, str) and message.strip():
        cleaned_message = message.strip()
        if cleaned_message == _OLD_DEFAULT_WELCOME_MESSAGE:
            cleaned_message = DEFAULT_WELCOME_MESSAGE
        welcome["message"] = cleaned_message[:MAX_WELCOME_MESSAGE_LENGTH]

    channel_id = raw.get("channel_id")
    if channel_id is not None:
        try:
            parsed_channel_id = int(channel_id)
        except (TypeError, ValueError):
            parsed_channel_id = 0
        welcome["channel_id"] = (
            parsed_channel_id if parsed_channel_id > 0 else None
        )

    welcome["enabled"] = bool(raw.get("enabled")) and welcome["channel_id"] is not None
    return welcome


def member_count_for_guild(guild: Any) -> int:
    count = getattr(guild, "member_count", None)
    if isinstance(count, int) and count > 0:
        return count
    members = getattr(guild, "members", None)
    if members is not None:
        try:
            return max(1, len(members))
        except TypeError:
            pass
    return 1


def render_welcome_text(
    template: str,
    *,
    member_id: int,
    username: str,
    guild_name: str,
    member_count: int = 0,
) -> str:
    values = {
        "user": f"<@{member_id}>",
        "username": escape_markdown(username),
        "server": escape_markdown(guild_name),
        "count": str(member_count),
    }

    def replace(match: re.Match[str]) -> str:
        return values[match.group(1)]

    return _PLACEHOLDER_RE.sub(replace, template)


def build_welcome_embed(
    guild: Any,
    member: Any,
    welcome: dict[str, Any] | None = None,
) -> discord.Embed:
    config = normalize_welcome(welcome)
    guild_name = str(getattr(guild, "name", None) or "сервер")
    member_id = int(getattr(member, "id", 0) or 0)
    display_name = str(
        getattr(member, "display_name", None)
        or getattr(member, "name", None)
        or "друг"
    )

    description = render_welcome_text(
        config["message"],
        member_id=member_id,
        username=display_name,
        guild_name=guild_name,
        member_count=member_count_for_guild(guild),
    )

    embed = discord.Embed(
        title=str(config["title"])[:256] or DEFAULT_WELCOME_TITLE,
        description=description[:4096],
        color=WELCOME_COLOR,
    )

    guild_icon = getattr(guild, "icon", None)
    icon_url = getattr(guild_icon, "url", None)
    if icon_url:
        embed.set_author(name=guild_name[:256], icon_url=icon_url)
    else:
        embed.set_author(name=guild_name[:256])

    avatar = getattr(member, "display_avatar", None)
    avatar_url = getattr(avatar, "url", None)
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)

    footer_text = f"{guild_name} · Новый участник"
    if icon_url:
        embed.set_footer(text=footer_text[:2048], icon_url=icon_url)
    else:
        embed.set_footer(text=footer_text[:2048])
    embed.timestamp = discord.utils.utcnow()
    return embed


async def send_welcome(store: Any, member: Any) -> bool:
    """Send the configured welcome message to a newly joined member."""

    if getattr(member, "bot", False):
        return False

    guild = getattr(member, "guild", None)
    if guild is None:
        return False

    settings = store.settings_for(getattr(guild, "id", 0))
    welcome = normalize_welcome(settings.get("welcome"))
    if not welcome["enabled"] or welcome["channel_id"] is None:
        return False

    channel = guild.get_channel(welcome["channel_id"])
    if channel is None or not hasattr(channel, "send"):
        log.warning(
            "Канал приветствия %s не найден или не является текстовым",
            welcome["channel_id"],
        )
        return False

    guild_me = getattr(guild, "me", None)
    permissions_for = getattr(channel, "permissions_for", None)
    if guild_me is not None and permissions_for is not None:
        permissions = permissions_for(guild_me)
        if not permissions.send_messages or not permissions.embed_links:
            log.warning(
                "Нет прав на отправку приветствия в канал %s",
                welcome["channel_id"],
            )
            return False

    embed = build_welcome_embed(guild, member, welcome)
    await channel.send(
        embed=embed,
        allowed_mentions=discord.AllowedMentions(
            everyone=False,
            roles=False,
            users=True,
            replied_user=False,
        ),
    )
    return True
