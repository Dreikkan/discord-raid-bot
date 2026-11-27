from __future__ import annotations

import unittest

from raidbot.constants import STATUS_ABSENT, STATUS_BENCH, STATUS_MAIN
from raidbot.registration import (
    count_main_for_role,
    effective_limits,
    has_main_tank,
    rebalance_waiting_tank,
    resolve_registration_status,
)


def make_raid(
    registrations: dict | None = None,
    *,
    tank_limit: int = 0,
    heal_limit: int = 2,
    dd_limit: int = 8,
) -> dict:
    return {
        "limits": {
            "tank": tank_limit,
            "heal": heal_limit,
            "dd": dd_limit,
        },
        "registrations": registrations or {},
    }


def players(
    role: str,
    count: int,
    status: str = STATUS_MAIN,
    *,
    start: int = 1,
) -> dict:
    return {
        str(user_id): {"status": status, "role": role}
        for user_id in range(start, start + count)
    }


class RegistrationTests(unittest.TestCase):
    def test_tank_can_join_main_when_dds_are_not_full(self) -> None:
        raid = make_raid(players("dd", 7))
        status, redirected, waiting = resolve_registration_status(
            raid, "8", "tank", STATUS_MAIN
        )
        self.assertEqual(status, STATUS_MAIN)
        self.assertFalse(redirected)
        self.assertFalse(waiting)

    def test_tank_goes_to_bench_when_dds_are_eight_of_eight(self) -> None:
        raid = make_raid(players("dd", 8))
        status, redirected, waiting = resolve_registration_status(
            raid, "9", "tank", STATUS_MAIN
        )
        self.assertEqual(status, STATUS_BENCH)
        self.assertTrue(redirected)
        self.assertTrue(waiting)

    def test_second_tank_waits_on_bench(self) -> None:
        registrations = players("tank", 1)
        registrations["1"]["updated_at"] = 1
        raid = make_raid(registrations)
        status, redirected, waiting = resolve_registration_status(
            raid, "2", "tank", STATUS_MAIN
        )
        self.assertEqual(status, STATUS_BENCH)
        self.assertTrue(redirected)
        self.assertTrue(waiting)

    def test_tank_bench_and_absent_are_not_waiting(self) -> None:
        raid = make_raid(players("dd", 8))
        self.assertEqual(
            resolve_registration_status(
                raid, "9", "tank", STATUS_BENCH
            ),
            (STATUS_BENCH, False, False),
        )
        self.assertEqual(
            resolve_registration_status(
                raid, "9", "tank", STATUS_ABSENT
            ),
            (STATUS_ABSENT, False, False),
        )

    def test_dd_has_eight_slots_without_tank(self) -> None:
        raid = make_raid(players("dd", 7))
        status, redirected, waiting = resolve_registration_status(
            raid, "8", "dd", STATUS_MAIN
        )
        self.assertEqual(status, STATUS_MAIN)
        self.assertFalse(redirected)
        self.assertFalse(waiting)

    def test_dd_has_seven_slots_when_tank_is_main(self) -> None:
        registrations = players("tank", 1)
        registrations.update(players("dd", 7, start=10))
        raid = make_raid(registrations)
        status, redirected, waiting = resolve_registration_status(
            raid, "20", "dd", STATUS_MAIN
        )
        self.assertEqual(status, STATUS_BENCH)
        self.assertTrue(redirected)
        self.assertFalse(waiting)

    def test_effective_limits_change_after_tank_join(self) -> None:
        raid = make_raid()
        self.assertEqual(
            effective_limits(raid), {"tank": 0, "heal": 2, "dd": 8}
        )
        raid["registrations"]["1"] = {
            "status": STATUS_MAIN,
            "role": "tank",
        }
        self.assertTrue(has_main_tank(raid))
        self.assertEqual(
            effective_limits(raid), {"tank": 1, "heal": 2, "dd": 7}
        )

    def test_waiting_tank_is_promoted_when_dd_slot_opens(self) -> None:
        registrations = players("dd", 7)
        registrations["100"] = {
            "status": STATUS_BENCH,
            "role": "tank",
            "waiting_for_tank_slot": True,
            "updated_at": 1,
        }
        raid = make_raid(registrations)
        promoted = rebalance_waiting_tank(raid)
        self.assertEqual(promoted, ["100"])
        self.assertEqual(
            raid["registrations"]["100"]["status"], STATUS_MAIN
        )
        self.assertFalse(
            raid["registrations"]["100"]["waiting_for_tank_slot"]
        )

    def test_waiting_tank_stays_bench_when_dd_is_eight_of_eight(self) -> None:
        registrations = players("dd", 8)
        registrations["100"] = {
            "status": STATUS_BENCH,
            "role": "tank",
            "waiting_for_tank_slot": True,
            "updated_at": 1,
        }
        raid = make_raid(registrations)
        self.assertEqual(rebalance_waiting_tank(raid), [])
        self.assertEqual(
            raid["registrations"]["100"]["status"], STATUS_BENCH
        )

    def test_dd_join_after_tank_is_main(self) -> None:
        registrations = players("tank", 1)
        registrations.update(players("dd", 6, start=10))
        raid = make_raid(registrations)
        status, _, _ = resolve_registration_status(
            raid, "20", "dd", STATUS_MAIN
        )
        self.assertEqual(status, STATUS_MAIN)

    def test_main_count_can_exclude_current_user(self) -> None:
        raid = make_raid(players("heal", 2))
        self.assertEqual(count_main_for_role(raid, "heal"), 2)
        self.assertEqual(
            count_main_for_role(raid, "heal", exclude_user_id="1"), 1
        )

    def test_unknown_status_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            resolve_registration_status(make_raid(), "1", "tank", "maybe")


if __name__ == "__main__":
    unittest.main()
