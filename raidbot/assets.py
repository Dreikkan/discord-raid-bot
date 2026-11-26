from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import discord

from .constants import ROLE_LABELS, ROLE_ORDER
from .store import Store

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ROLE_ICON_DIR = PROJECT_ROOT / "assets" / "role_icons"
SPEC_ICON_DIR = PROJECT_ROOT / "assets" / "spec_icons"

ROLE_ICON_FILES: dict[str, Path] = {
    "tank": ROLE_ICON_DIR / "tank.png",
    "heal": ROLE_ICON_DIR / "heal.png",
    "dd": ROLE_ICON_DIR / "dd.png",
}
ROLE_EMOJI_NAMES: dict[str, str] = {
    "tank": "raid_tank",
    "heal": "raid_heal",
    "dd": "raid_dd",
}

_EMOJI_SIZE_LIMIT = 256 * 1024
_locks: dict[int, asyncio.Lock] = {}


@dataclass(slots=True)
class RoleIconSyncResult:
    updated: bool = False
    uploaded: int = 0
    emojis: dict[str, str] = field(default_factory=dict)
    error: str | None = None


@dataclass(slots=True)
class SpecIconSyncResult:
    updated: bool = False
    uploaded: int = 0
    emojis: dict[str, str] = field(default_factory=dict)
    error: str | None = None


def _lock_for(guild_id: int) -> asyncio.Lock:
    lock = _locks.get(guild_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[guild_id] = lock
    return lock


def emoji_tag(emoji: Any) -> str:
    prefix = "a" if getattr(emoji, "animated", False) else ""
    return f"<{prefix}:{emoji.name}:{emoji.id}>"


def _all_icons_are_custom(settings: dict[str, Any]) -> bool:
    role_emojis = settings.get("role_emojis", {})
    return all(str(role_emojis.get(role, "")).startswith("<") for role in ROLE_ORDER)


async def sync_role_icons(
    guild: Any,
    store: Store,
    *,
    force: bool = False,
) -> RoleIconSyncResult:
    """Upload the bundled PNG role icons as guild emojis and save their tags.

    Existing emojis with the reserved names are reused, so callers can safely
    call this repeatedly. Manual icon settings are left alone unless
    ``force=True`` (used by the explicit reload command).
    """

    async with _lock_for(int(guild.id)):
        settings = store.settings_for(guild.id)
        if not force and settings.get("role_icons_source") == "manual":
            return RoleIconSyncResult(emojis=dict(settings.get("role_emojis", {})))

        # Avoid an API call on every raid creation after a successful sync.
        if (
            not force
            and settings.get("role_icons_source") == "assets"
            and _all_icons_are_custom(settings)
        ):
            return RoleIconSyncResult(emojis=dict(settings.get("role_emojis", {})))

        errors: list[str] = []
        existing = {emoji.name: emoji for emoji in getattr(guild, "emojis", [])}

        try:
            fetched = await guild.fetch_emojis()
        except (discord.HTTPException, AttributeError):
            log.exception("Не удалось получить список эмодзи сервера %s", guild.id)
        else:
            existing = {emoji.name: emoji for emoji in fetched}

        me = getattr(guild, "me", None)
        permissions = getattr(me, "guild_permissions", None)
        can_manage = bool(permissions and permissions.manage_expressions)

        new_emojis: dict[str, str] = {}
        uploaded = 0

        for role in ROLE_ORDER:
            path = ROLE_ICON_FILES[role]
            if not path.is_file():
                errors.append(f"нет файла {path.name} для роли «{ROLE_LABELS[role]}»")
                continue

            emoji_name = ROLE_EMOJI_NAMES[role]
            emoji = existing.get(emoji_name)

            if emoji is None:
                if not can_manage:
                    errors.append(
                        f"нет права «Управлять выражениями» для загрузки иконки "
                        f"«{ROLE_LABELS[role]}»"
                    )
                    continue

                try:
                    image = path.read_bytes()
                except OSError:
                    log.exception("Не удалось прочитать иконку %s", path)
                    errors.append(f"не удалось прочитать файл {path.name}")
                    continue

                if len(image) > _EMOJI_SIZE_LIMIT:
                    errors.append(f"файл {path.name} больше 256 КБ")
                    continue

                try:
                    emoji = await guild.create_custom_emoji(
                        name=emoji_name,
                        image=image,
                        reason="Иконки ролей для эмбеда рейда",
                    )
                except (discord.HTTPException, ValueError, TypeError):
                    log.exception(
                        "Не удалось загрузить emoji %s на сервер %s",
                        emoji_name,
                        guild.id,
                    )
                    errors.append(f"не удалось загрузить иконку «{ROLE_LABELS[role]}»")
                    continue

                uploaded += 1
                existing[emoji_name] = emoji

            new_emojis[role] = emoji_tag(emoji)

        if not new_emojis:
            return RoleIconSyncResult(
                error="; ".join(errors) if errors else None,
            )

        changed = any(
            settings.get("role_emojis", {}).get(role) != value
            for role, value in new_emojis.items()
        )
        if changed or force:
            store.set_role_emojis(
                guild.id, new_emojis, source="assets"
            )

        return RoleIconSyncResult(
            updated=changed,
            uploaded=uploaded,
            emojis=new_emojis,
            error="; ".join(errors) if errors else None,
        )


def _spec_emoji_name(icon_file: str) -> str:
    stem = Path(icon_file).stem.casefold()
    safe = re.sub(r"[^a-z0-9_]+", "_", stem).strip("_") or "icon"
    return f"raid_spec_{safe}"[:32]


async def sync_spec_icons(
    guild: Any,
    store: Store,
    *,
    force: bool = False,
) -> SpecIconSyncResult:
    """Upload specialization icon files as guild emojis and save their tags."""

    async with _lock_for(int(guild.id)):
        settings = store.settings_for(guild.id)
        specs = settings.get("specs", [])
        targets = [
            spec
            for spec in specs
            if spec.get("icon_file")
            and (
                force
                or not str(spec.get("emoji", "")).startswith("<")
            )
        ]
        if not targets:
            return SpecIconSyncResult()

        errors: list[str] = []
        existing = {emoji.name: emoji for emoji in getattr(guild, "emojis", [])}

        try:
            fetched = await guild.fetch_emojis()
        except (discord.HTTPException, AttributeError):
            log.exception("Не удалось получить список эмодзи сервера %s", guild.id)
        else:
            existing = {emoji.name: emoji for emoji in fetched}

        me = getattr(guild, "me", None)
        permissions = getattr(me, "guild_permissions", None)
        can_manage = bool(permissions and permissions.manage_expressions)

        new_emojis: dict[str, str] = {}
        uploaded = 0

        for spec in targets:
            path = SPEC_ICON_DIR / Path(str(spec["icon_file"])).name
            if not path.is_file():
                errors.append(
                    f"нет файла {path.name} для «{spec['name']}»"
                )
                continue

            emoji_name = _spec_emoji_name(path.name)
            emoji = existing.get(emoji_name)

            if emoji is None:
                if not can_manage:
                    errors.append(
                        f"нет права «Управлять выражениями» для загрузки иконки "
                        f"«{spec['name']}»"
                    )
                    continue

                try:
                    image = path.read_bytes()
                except OSError:
                    log.exception("Не удалось прочитать иконку %s", path)
                    errors.append(f"не удалось прочитать файл {path.name}")
                    continue

                if len(image) > _EMOJI_SIZE_LIMIT:
                    errors.append(f"файл {path.name} больше 256 КБ")
                    continue

                try:
                    emoji = await guild.create_custom_emoji(
                        name=emoji_name,
                        image=image,
                        reason=f"Иконка специализации {spec['name']}",
                    )
                except (discord.HTTPException, ValueError, TypeError):
                    log.exception(
                        "Не удалось загрузить emoji %s на сервер %s",
                        emoji_name,
                        guild.id,
                    )
                    errors.append(
                        f"не удалось загрузить иконку «{spec['name']}»"
                    )
                    continue

                uploaded += 1
                existing[emoji_name] = emoji

            new_emojis[str(spec["id"])] = emoji_tag(emoji)

        old_emojis = {
            str(spec["id"]): str(spec.get("emoji", "")) for spec in specs
        }
        changed = any(
            old_emojis.get(spec_id) != value
            for spec_id, value in new_emojis.items()
        )
        if changed:
            store.set_spec_emojis(guild.id, new_emojis)

        return SpecIconSyncResult(
            updated=changed,
            uploaded=uploaded,
            emojis=new_emojis,
            error="; ".join(errors) if errors else None,
        )
