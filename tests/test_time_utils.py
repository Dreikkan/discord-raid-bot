from __future__ import annotations

import unittest
from datetime import date, datetime, time, timezone

from raidbot.time_utils import (
    TimeInputError,
    combine_date_time,
    format_timestamp,
    parse_start_at,
    parse_time_value,
    parse_timezone,
)


class TimeUtilsTests(unittest.TestCase):
    def test_moscow_time_converts_to_utc(self) -> None:
        timestamp = parse_start_at("26.10.2026", "20:30", "Europe/Moscow")
        actual = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        self.assertEqual(actual, datetime(2026, 10, 26, 17, 30, tzinfo=timezone.utc))

    def test_date_formats_are_supported(self) -> None:
        expected = parse_start_at("26.10.2026", "20:30", "Europe/Moscow")
        self.assertEqual(
            parse_start_at("2026-10-26", "20:30", "Europe/Moscow"), expected
        )
        self.assertEqual(
            parse_start_at("26/10/2026", "20.30", "Europe/Moscow"), expected
        )

    def test_msk_alias_and_offset(self) -> None:
        name, zone = parse_timezone("МСК")
        self.assertEqual(name, "Europe/Moscow")
        self.assertIsNotNone(zone)

        name, _ = parse_timezone("UTC+3")
        self.assertEqual(name, "UTC+03:00")

        self.assertEqual(
            parse_start_at("26.10.2026", "20:30", "UTC+3"),
            parse_start_at("26.10.2026", "20:30", "Europe/Moscow"),
        )

    def test_invalid_inputs(self) -> None:
        with self.assertRaises(TimeInputError):
            parse_start_at("31.02.2026", "20:30", "Europe/Moscow")
        with self.assertRaises(TimeInputError):
            parse_start_at("26.10.2026", "25:00", "Europe/Moscow")
        with self.assertRaises(TimeInputError):
            parse_timezone("Mars/Olympus")

    def test_dst_gap_is_rejected(self) -> None:
        with self.assertRaises(TimeInputError):
            parse_start_at("29.03.2026", "02:30", "Europe/Berlin")

    def test_timestamp_markup(self) -> None:
        self.assertEqual(format_timestamp(123, "t"), "<t:123:t>")

    def test_parse_time_and_combine_date(self) -> None:
        self.assertEqual(parse_time_value("20:30"), time(20, 30))
        self.assertEqual(parse_time_value("20.30"), time(20, 30))
        self.assertEqual(
            combine_date_time(
                date(2026, 10, 26), time(20, 30), "Europe/Moscow"
            ),
            parse_start_at("26.10.2026", "20:30", "Europe/Moscow"),
        )
        with self.assertRaises(TimeInputError):
            parse_time_value("25:00")


if __name__ == "__main__":
    unittest.main()
