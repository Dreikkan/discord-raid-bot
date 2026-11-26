from __future__ import annotations

from typing import Any

import discord

from .constants import (
    ABSENT_EMOJI,
    BENCH_EMOJI,
    EMBED_COLOR,
    EMBED_TOTAL_SOFT_LIMIT,
    ROLE_LABELS,
    ROLE_ORDER,
    STATUS_ABSENT,
    STATUS_BENCH,
    STATUS_MAIN,
)
from .text import escape_markdown

_FIELD_VALUE_LIMIT = 1024


def _display_name(registration: dict[str, Any], fallback: str) -> str:
    name = str(registration.get("display_name") or "").strip()
    if not name:
        name = fallback
    return escape_markdown(name)


def _player_label(user_id: str, registration: dict[str, Any]) -> str:
    emoji = str(registration.get("spec_emoji") or "").strip()
    name = _display_name(registration, f"<@{user_id}>")
    return f"{emoji} {name}".strip()


def _format_players(
    players: list[tuple[str, dict[str, Any]]],
    *,
    separator: str,
    limit: int = _FIELD_VALUE_LIMIT,
) -> str:
    if not players:
        return "—"

    entries = [_player_label(user_id, registration) for user_id, registration in players]
    rendered: list[str] = []

    for index, entry in enumerate(entries):
        if len(entry) > limit:
            if not rendered:
                return f"{entry[: limit - 1]}…"
            entry = f"{entry[: max(1, limit - 1)]}…"

        candidate = separator.join([*rendered, entry])
        remaining_after_candidate = len(entries) - index - 1
        if len(candidate) <= limit and remaining_after_candidate == 0:
            rendered.append(entry)
            continue

        if len(candidate) <= limit:
            # It fits now, but a later item might not. Add it and decide later.
            rendered.append(entry)
            continue

        if not rendered:
            return f"{entry[: limit - 1]}…"

        suffix = f"{separator}… и ещё {len(entries) - len(rendered)}"
        while rendered and len(separator.join(rendered)) + len(suffix) > limit:
            rendered.pop()

        if not rendered:
            return f"{entry[: limit - 1]}…"
        return separator.join(rendered) + suffix

    return separator.join(rendered)


def _role_field_name(raid: dict[str, Any], role: str, count: int) -> str:
    emoji = str(raid.get("role_emojis", {}).get(role, "")).strip()
    limit = int(raid.get("limits", {}).get(role, 0))
    label = f"{ROLE_LABELS[role]} ({count}/{limit})"
    return f"{emoji} {label}".strip()


def _fit_total_length(embed: discord.Embed) -> None:
    """Trim the longest field value in the rare case an embed exceeds 6000 chars."""

    def total_length() -> int:
        total = len(embed.title or "")
        total += len(embed.description or "")
        if embed.footer and embed.footer.text:
            total += len(embed.footer.text)
        if embed.author and embed.author.name:
            total += len(embed.author.name)
        fields = getattr(embed, "_fields", [])
        for field in fields:
            total += len(field.get("name", "")) + len(field.get("value", ""))
        return total

    total = total_length()
    while total > EMBED_TOTAL_SOFT_LIMIT:
        fields = getattr(embed, "_fields", [])
        if not fields:
            break
        longest = max(fields, key=lambda field: len(field.get("value", "")))
        value = longest.get("value", "")
        if len(value) <= 40:
            break

        overflow = total - EMBED_TOTAL_SOFT_LIMIT
        keep = max(20, len(value) - overflow - 1)
        longest["value"] = f"{value[:keep].rstrip()}…"
        total = total_length()


def build_raid_embed(raid: dict[str, Any]) -> discord.Embed:
    registrations: dict[str, dict[str, Any]] = raid.get("registrations", {})
    start_at = int(raid["start_at"])

    description_lines = [
        "**Запись на рейд**",
        f"**Дата:** <t:{start_at}:D>",
        f"**Время:** <t:{start_at}:t> · <t:{start_at}:R>",
    ]

    user_description = str(raid.get("description") or "").strip()
    if user_description:
        description_lines.extend(("", user_description))

    embed = discord.Embed(
        title=str(raid.get("title") or "Рейд"),
        description="\n".join(description_lines),
        color=EMBED_COLOR,
    )

    for role in ROLE_ORDER:
        players = [
            (user_id, registration)
            for user_id, registration in registrations.items()
            if registration.get("status") == STATUS_MAIN
            and registration.get("role") == role
        ]
        embed.add_field(
            name=_role_field_name(raid, role, len(players)),
            value=_format_players(players, separator="\n"),
            inline=True,
        )

    bench_players = [
        (user_id, registration)
        for user_id, registration in registrations.items()
        if registration.get("status") == STATUS_BENCH
    ]
    absent_players = [
        (user_id, registration)
        for user_id, registration in registrations.items()
        if registration.get("status") == STATUS_ABSENT
    ]

    embed.add_field(
        name=f"{BENCH_EMOJI} Скамья запасных ({len(bench_players)})",
        value=_format_players(bench_players, separator=", "),
        inline=False,
    )
    embed.add_field(
        name=f"{ABSENT_EMOJI} Буду отсутствовать ({len(absent_players)})",
        value=_format_players(absent_players, separator=", "),
        inline=False,
    )

    embed.set_footer(
        text="Время отображается в вашем часовом поясе • Запись — кнопкой «Зарегистрироваться»"
    )

    _fit_total_length(embed)
    return embed

