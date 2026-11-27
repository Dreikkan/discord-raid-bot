from __future__ import annotations

import time
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


def has_main_tank(raid: dict[str, Any]) -> bool:
    return any(
        registration.get("status") == STATUS_MAIN
        and registration.get("role") == "tank"
        for registration in raid.get("registrations", {}).values()
    )


def effective_limits(raid: dict[str, Any]) -> dict[str, int]:
    limits = raid.get("limits", {})
    base_tank = max(0, int(limits.get("tank", 0)))
    heal = max(0, int(limits.get("heal", 0)))
    dd = max(0, int(limits.get("dd", 0)))
    if has_main_tank(raid):
        return {
            "tank": max(1, base_tank + 1),
            "heal": heal,
            "dd": max(0, dd - 1),
        }
    return {"tank": base_tank, "heal": heal, "dd": dd}


def resolve_registration_status(
    raid: dict[str, Any],
    user_id: str | int,
    role: str,
    requested_status: str,
) -> tuple[str, bool, bool]:
    """Return (effective_status, redirected_to_bench, waiting_tank)."""

    if requested_status not in {STATUS_MAIN, STATUS_BENCH, STATUS_ABSENT}:
        raise ValueError(f"Unknown status: {requested_status}")

    if requested_status in {STATUS_BENCH, STATUS_ABSENT}:
        return requested_status, False, False

    if role not in ROLE_ORDER:
        raise ValueError(f"Unknown role: {role}")

    limits = raid.get("limits", {})
    if role == "tank":
        base_tank = max(0, int(limits.get("tank", 0)))
        base_dd = max(0, int(limits.get("dd", 0)))
        main_tanks = count_main_for_role(
            raid, "tank", exclude_user_id=str(user_id)
        )
        dd_main = count_main_for_role(
            raid, "dd", exclude_user_id=str(user_id)
        )
        if main_tanks >= base_tank + 1 or dd_main >= base_dd:
            return STATUS_BENCH, True, True
        return STATUS_MAIN, False, False

    effective = effective_limits(raid)
    limit = int(effective.get(role, 0))
    occupied = count_main_for_role(
        raid, role, exclude_user_id=str(user_id)
    )
    if occupied >= limit:
        return STATUS_BENCH, True, False

    return STATUS_MAIN, False, False


def rebalance_waiting_tank(raid: dict[str, Any]) -> list[str]:
    """Promote the earliest waiting tank when a slot opens."""

    if has_main_tank(raid):
        return []

    limits = raid.get("limits", {})
    base_dd = max(0, int(limits.get("dd", 0)))
    dd_main = count_main_for_role(raid, "dd")
    if dd_main >= base_dd:
        return []

    waiting = [
        (str(user_id), registration)
        for user_id, registration in raid.get("registrations", {}).items()
        if registration.get("role") == "tank"
        and registration.get("status") == STATUS_BENCH
        and registration.get("waiting_for_tank_slot")
    ]
    if not waiting:
        return []

    user_id, registration = min(
        waiting,
        key=lambda item: int(item[1].get("updated_at", 0)),
    )
    registration["status"] = STATUS_MAIN
    registration["waiting_for_tank_slot"] = False
    registration["updated_at"] = int(time.time())
    return [user_id]
