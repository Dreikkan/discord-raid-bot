from __future__ import annotations

import re

import discord

from .constants import ROLE_ALIASES

_CUSTOM_EMOJI_RE = re.compile(
    r"^<(a?):([A-Za-z0-9_]{2,32}):([0-9]{15,22})>$",
    re.IGNORECASE,
)


class SpecInputError(ValueError):
    """Raised for an invalid specialization emoji."""


def normalize_role(value: str) -> str | None:
    return ROLE_ALIASES.get((value or "").strip().casefold())


def normalize_emoji(value: str, *, required: bool = True) -> str:
    """Validate a Unicode emoji or a Discord custom emoji tag."""

    raw = (value or "").strip()
    if raw.startswith("\\<:"):
        raw = raw[1:]

    if not raw:
        if required:
            raise SpecInputError("Укажите иконку специализации.")
        return ""

    if "\n" in raw or "\r" in raw or "\t" in raw:
        raise SpecInputError("Иконка не должна содержать переносов строк.")

    if raw.startswith("<"):
        match = _CUSTOM_EMOJI_RE.fullmatch(raw)
        if not match:
            raise SpecInputError(
                "Неверный тег кастомного emoji. Нужен вид <:название:ID>."
            )
        return raw

    if len(raw) > 64:
        raise SpecInputError("Иконка слишком длинная.")

    return raw


def to_partial_emoji(value: str) -> discord.PartialEmoji | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return discord.PartialEmoji.from_str(raw)
    except (ValueError, TypeError):
        return None
