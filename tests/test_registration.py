from __future__ import annotations

import unittest

from raidbot.constants import STATUS_ABSENT, STATUS_BENCH, STATUS_MAIN
from raidbot.registration import (
    count_main_for_role,
    resolve_requested_status,
    should_redirect_dd_to_tank,
)


def make_raid(registrations: dict | None = None, tank_limit: int = 2) -> dict:
    return {
        "limits": {"tank": tank_limit, "heal": 2, "dd": 3},
        "registrations": registrations or {},
    }


class RegistrationTests(unittest.TestCase):
    def test_join_becomes_bench_when_role_is_full(self) -> None:
        raid = make_raid(
            {
                "1": {"status": STATUS_MAIN, "role": "tank"},
                "2": {"status": STATUS_MAIN, "role": "tank"},
            }
        )
        status, redirected = resolve_requested_status(raid, "3", "tank", STATUS_MAIN)
        self.assertEqual(status, STATUS_BENCH)
        self.assertTrue(redirected)

    def test_join_stays_main_when_role_has_space(self) -> None:
        raid = make_raid({"1": {"status": STATUS_MAIN, "role": "tank"}})
        status, redirected = resolve_requested_status(raid, "2", "tank", STATUS_MAIN)
        self.assertEqual(status, STATUS_MAIN)
        self.assertFalse(redirected)

    def test_existing_main_does_not_consume_a_second_slot(self) -> None:
        raid = make_raid(
            {
                "1": {"status": STATUS_MAIN, "role": "tank"},
                "2": {"status": STATUS_MAIN, "role": "tank"},
            },
            tank_limit=2,
        )
        status, redirected = resolve_requested_status(raid, "1", "tank", STATUS_MAIN)
        self.assertEqual(status, STATUS_MAIN)
        self.assertFalse(redirected)

    def test_bench_and_absent_are_never_redirected(self) -> None:
        raid = make_raid(
            {
                "1": {"status": STATUS_MAIN, "role": "tank"},
                "2": {"status": STATUS_MAIN, "role": "tank"},
            }
        )
        self.assertEqual(
            resolve_requested_status(raid, "3", "tank", STATUS_BENCH),
            (STATUS_BENCH, False),
        )
        self.assertEqual(
            resolve_requested_status(raid, "3", "tank", STATUS_ABSENT),
            (STATUS_ABSENT, False),
        )

    def test_main_count_can_exclude_current_user(self) -> None:
        raid = make_raid(
            {
                "1": {"status": STATUS_MAIN, "role": "heal"},
                "2": {"status": STATUS_MAIN, "role": "heal"},
                "3": {"status": STATUS_BENCH, "role": "heal"},
            }
        )
        self.assertEqual(count_main_for_role(raid, "heal"), 2)
        self.assertEqual(count_main_for_role(raid, "heal", exclude_user_id="1"), 1)

    def test_unknown_status_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            resolve_requested_status(make_raid(), "1", "tank", "maybe")

    def test_full_dd_group_sends_next_dd_to_tank(self) -> None:
        raid = {
            "limits": {"tank": 1, "heal": 2, "dd": 7},
            "registrations": {
                str(user_id): {"status": STATUS_MAIN, "role": "dd"}
                for user_id in range(1, 8)
            },
        }
        self.assertTrue(
            should_redirect_dd_to_tank(raid, "8", "dd", STATUS_MAIN)
        )
        self.assertFalse(
            should_redirect_dd_to_tank(raid, "8", "dd", STATUS_BENCH)
        )

    def test_dd_overflow_is_not_repeated(self) -> None:
        raid = {
            "limits": {"tank": 2, "heal": 2, "dd": 7},
            "registrations": {
                **{
                    str(user_id): {"status": STATUS_MAIN, "role": "dd"}
                    for user_id in range(1, 8)
                },
                "100": {
                    "status": STATUS_MAIN,
                    "role": "tank",
                    "converted_from_dd": True,
                },
            },
        }
        self.assertFalse(
            should_redirect_dd_to_tank(raid, "8", "dd", STATUS_MAIN)
        )

    def test_dd_overflow_requires_free_tank_slot(self) -> None:
        raid = {
            "limits": {"tank": 1, "heal": 2, "dd": 7},
            "registrations": {
                **{
                    str(user_id): {"status": STATUS_MAIN, "role": "dd"}
                    for user_id in range(1, 8)
                },
                "100": {"status": STATUS_MAIN, "role": "tank"},
            },
        }
        self.assertFalse(
            should_redirect_dd_to_tank(raid, "8", "dd", STATUS_MAIN)
        )


if __name__ == "__main__":
    unittest.main()
