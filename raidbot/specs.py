from __future__ import annotations

import re
from typing import Any

import discord

from .constants import (
    MAX_SPEC_NAME_LENGTH,
    MAX_SPECS_PER_ROLE,
    ROLE_ALIASES,
    ROLE_LABELS,
    ROLE_ORDER,
)

_CUSTOM_EMOJI_RE = re.compile(
    r"^<(a?):([A-Za-z0-9_]{2,32}):([0-9]{15,22})>$",
    re.IGNORECASE,
)


class SpecImportError(ValueError):
    """Raised for an invalid specialization name/icon or import file."""


def normalize_role(value: str) -> str | None:
    return ROLE_ALIASES.get((value or "").strip().casefold())


def normalize_emoji(value: str, *, required: bool = True) -> str:
    """Validate a Unicode emoji or a Discord custom emoji tag.

    Custom emoji must already exist in the guild; the bot stores the tag
    (for example ``<:guard:123456789012345678>``).
    """

    raw = (value or "").strip()
    if raw.startswith("\\<:"):
        raw = raw[1:]

    if not raw:
        if required:
            raise SpecImportError("Укажите иконку: emoji или тег кастомного emoji.")
        return ""

    if "\n" in raw or "\r" in raw or "\t" in raw:
        raise SpecImportError("Иконка не должна содержать переносов строк.")

    if raw.startswith("<"):
        match = _CUSTOM_EMOJI_RE.fullmatch(raw)
        if not match:
            raise SpecImportError(
                "Неверный тег кастомного emoji. Нужен вид <:название:ID> "
                "или <a:название:ID>."
            )
        return raw

    if len(raw) > 64:
        raise SpecImportError("Иконка слишком длинная.")

    return raw


def to_partial_emoji(value: str) -> discord.PartialEmoji | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return discord.PartialEmoji.from_str(raw)
    except (ValueError, TypeError):
        return None


def _clean_name(value: Any) -> str:
    name = str(value or "").strip()
    if not name:
        raise SpecImportError("У одной из специализаций не указано название.")
    if "\n" in name or "\r" in name:
        raise SpecImportError("Название специализации не должно содержать переносов строк.")
    if len(name) > MAX_SPEC_NAME_LENGTH:
        raise SpecImportError(
            f"Название «{name[:30]}…» длиннее {MAX_SPEC_NAME_LENGTH} символов."
        )
    return name


def _clean_spec(role_value: Any, name_value: Any, emoji_value: Any) -> dict[str, str]:
    role = normalize_role(str(role_value or ""))
    if role is None:
        raise SpecImportError(
            "Неизвестная роль. Допустимо: tank/танк, heal/хил, dd/дд."
        )
    name = _clean_name(name_value)
    emoji = normalize_emoji(str(emoji_value or ""), required=True)
    return {"role": role, "name": name, "emoji": emoji}


def parse_specs_payload(payload: Any) -> list[dict[str, str]]:
    """Accept both grouped and flat JSON formats for specialization import."""

    raw_specs: list[dict[str, str]] = []

    if isinstance(payload, dict) and isinstance(payload.get("specs"), list):
        payload = payload["specs"]

    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                raise SpecImportError("Каждый элемент списка должен быть объектом JSON.")
            raw_specs.append(
                _clean_spec(item.get("role"), item.get("name"), item.get("emoji"))
            )
    elif isinstance(payload, dict):
        for role_key, role_items in payload.items():
            role = normalize_role(str(role_key))
            if role is None:
                raise SpecImportError(f"Неизвестная роль в файле: {role_key!r}.")
            if not isinstance(role_items, list):
                raise SpecImportError(f"Значение для роли «{role_key}» должно быть списком.")

            for item in role_items:
                if not isinstance(item, dict):
                    raise SpecImportError(
                        "В группированном формате элементы ролей должны быть объектами."
                    )
                raw_specs.append(
                    _clean_spec(role, item.get("name"), item.get("emoji"))
                )
    else:
        raise SpecImportError(
            "Ожидался JSON-массив или объект, сгруппированный по ролям."
        )

    if not raw_specs:
        raise SpecImportError("В файле нет ни одной специализации.")

    deduplicated: dict[tuple[str, str], dict[str, str]] = {}
    for spec in raw_specs:
        key = (spec["role"], spec["name"].casefold())
        deduplicated[key] = spec

    result = list(deduplicated.values())
    counts = {role: 0 for role in ROLE_ORDER}
    for spec in result:
        counts[spec["role"]] += 1

    for role, count in counts.items():
        if count > MAX_SPECS_PER_ROLE:
            raise SpecImportError(
                f"Для роли «{ROLE_LABELS[role]}» указано {count} специализаций. "
                f"Discord позволяет не больше {MAX_SPECS_PER_ROLE} в одном меню."
            )

    return result
