from __future__ import annotations

import unittest
from datetime import date, time

from raidbot.activities import (
    ActivityError,
    activity_defaults,
    activity_end_at,
    format_schedules,
    next_activity_occurrence,
    parse_schedules,
)
from raidbot.time_utils import combine_date_time


class ActivityScheduleTests(unittest.TestCase):
    def test_seeded_activities(self) -> None:
        activities = activity_defaults()
        names = {activity["name"] for activity in activities}
        self.assertEqual(
            names,
            {
                "Вечеринка",
                "Разгром армии (Босс)",
                "PvP Арена",
                "Война гильдий",
            },
        )
        self.assertTrue(all(activity["schedules"] for activity in activities))
        self.assertTrue(all(activity["channel_id"] is None for activity in activities))

    def test_parse_weekly_schedules(self) -> None:
        schedules = parse_schedules(
            "Вторник 20:00-22:00; Суббота 19:00-21:00"
        )
        self.assertEqual(
            schedules,
            [
                {"weekday": 1, "start": "20:00", "end": "22:00"},
                {"weekday": 5, "start": "19:00", "end": "21:00"},
            ],
        )
        self.assertIn("Вторник", format_schedules(schedules))

    def test_parse_daily_and_short_weekday_names(self) -> None:
        self.assertEqual(
            parse_schedules("Ежедневно 21:00-21:30"),
            [{"weekday": None, "start": "21:00", "end": "21:30"}],
        )
        self.assertEqual(
            parse_schedules("чт 19:30-21:30; вс 18:30-20:30"),
            [
                {"weekday": 3, "start": "19:30", "end": "21:30"},
                {"weekday": 6, "start": "18:30", "end": "20:30"},
            ],
        )

    def test_invalid_schedule_is_rejected(self) -> None:
        with self.assertRaises(ActivityError):
            parse_schedules("Когда-нибудь 20:00-22:00")
        with self.assertRaises(ActivityError):
            parse_schedules("Вторник 22:00")

    def test_next_occurrence_and_cross_midnight_end(self) -> None:
        activity = {
            "schedules": [
                {"weekday": 5, "start": "21:30", "end": "00:00"}
            ]
        }
        after = int(
            combine_date_time(date(2026, 11, 27), time(12, 0), "Europe/Moscow")
        )
        occurrence = next_activity_occurrence(
            activity, "Europe/Moscow", after_ts=after
        )
        self.assertIsNotNone(occurrence)
        assert occurrence is not None
        start_at, schedule = occurrence
        end_at = activity_end_at(schedule, "Europe/Moscow", start_at)
        self.assertGreater(end_at, start_at)
        self.assertGreaterEqual(end_at - start_at, 2 * 60 * 60)


if __name__ == "__main__":
    unittest.main()
