from __future__ import annotations

from typing import Any

from .constants import ROLE_ORDER, STATUS_ABSENT, STATUS_BENCH, STATUS_MAIN


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
