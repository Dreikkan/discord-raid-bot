from __future__ import annotations

from typing import Any

from .constants import ROLE_ORDER, STATUS_ABSENT, STATUS_BENCH, STATUS_MAIN


def registration_specializations(
    registration: dict[str, Any],
) -> list[dict[str, str]]:
    """Return up to two specializations, supporting old single-spec records."""

    raw_specs = registration.get("specializations")
    if isinstance(raw_specs, list):
        specs: list[dict[str, str]] = []
        for raw in raw_specs[:2]:
            if not isinstance(raw, dict):
                continue
            specs.append(
                {
                    "id": str(raw.get("id", "")),
                    "name": str(raw.get("name", "")),
                    "emoji": str(raw.get("emoji", "")),
                }
            )
        if specs:
            return specs

    # Backward compatibility with registrations created before dual specs.
    if registration.get("spec_id") or registration.get("spec_name"):
        return [
            {
                "id": str(registration.get("spec_id", "")),
                "name": str(registration.get("spec_name", "")),
                "emoji": str(registration.get("spec_emoji", "")),
            }
        ]

    return []


def count_main_for_role(raid: dict[str, Any], role: str, *, exclude_user_id: str | None = None) -> int:
    count = 0
    for user_id, registration in raid.get("registrations", {}).items():
        if exclude_user_id is not None and str(user_id) == str(exclude_user_id):
            continue
        if (
            registration.get("status") == STATUS_MAIN
            and registration.get("role") == role
        ):
            count += 1
    return count


def should_redirect_dd_to_tank(
    raid: dict[str, Any],
    user_id: str | int,
    role: str,
    requested_status: str,
) -> bool:
    """Return True when the next joining DD should take a free tank slot."""

    if role != "dd" or requested_status != STATUS_MAIN:
        return False

    limits = raid.get("limits", {})
    dd_limit = max(0, int(limits.get("dd", 0)))
    tank_limit = max(0, int(limits.get("tank", 0)))
    if tank_limit <= 0:
        return False

    dd_main = count_main_for_role(
        raid, "dd", exclude_user_id=str(user_id)
    )
    if dd_main < dd_limit:
        return False

    # Only one overflow DD becomes a tank for a given raid.
    for registration in raid.get("registrations", {}).values():
        if (
            registration.get("converted_from_dd")
            and registration.get("status") == STATUS_MAIN
        ):
            return False

    tank_main = count_main_for_role(
        raid, "tank", exclude_user_id=str(user_id)
    )
    return tank_main < tank_limit


def resolve_requested_status(
    raid: dict[str, Any],
    user_id: str | int,
    role: str,
    requested_status: str,
) -> tuple[str, bool]:
    """Return (effective_status, was_redirected_to_bench)."""

    if requested_status not in {STATUS_MAIN, STATUS_BENCH, STATUS_ABSENT}:
        raise ValueError(f"Unknown status: {requested_status}")

    if requested_status in {STATUS_BENCH, STATUS_ABSENT}:
        return requested_status, False

    if role not in ROLE_ORDER:
        raise ValueError(f"Unknown role: {role}")

    limit = int(raid.get("limits", {}).get(role, 0))
    occupied = count_main_for_role(raid, role, exclude_user_id=str(user_id))
    if occupied >= max(limit, 0):
        return STATUS_BENCH, True

    return STATUS_MAIN, False
