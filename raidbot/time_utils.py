from __future__ import annotations

import re
from datetime import (
    date as date_type,
    datetime,
    time as time_type,
    timedelta,
    timezone,
    tzinfo,
)
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_DATE_FORMATS = ("%d.%m.%Y", "%d.%m.%y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d")
_TIME_FORMATS = ("%H:%M", "%H.%M")

_OFFSET_RE = re.compile(
    r"^(?:(UTC|GMT)\s*)?([+-])(\d{1,2})(?::?(\d{2}))?$",
    re.IGNORECASE,
)

_TIMEZONE_ALIASES = {
    "мск": "Europe/Moscow",
    "msk": "Europe/Moscow",
    "москва": "Europe/Moscow",
    "moscow": "Europe/Moscow",
    "utc": "UTC",
    "gmt": "UTC",
    "z": "UTC",
}


class TimeInputError(ValueError):
    """Raised when the administrator supplied an invalid date/time/timezone."""


def parse_timezone(value: str) -> tuple[str, tzinfo]:
    """Return a canonical timezone name and a tzinfo instance."""

    raw = (value or "").strip()
    if not raw:
        raise TimeInputError("Укажите часовой пояс, например Europe/Moscow.")

    alias = _TIMEZONE_ALIASES.get(raw.casefold())
    if alias:
        if alias == "UTC":
            return "UTC", timezone.utc
        return alias, ZoneInfo(alias)

    offset_match = _OFFSET_RE.fullmatch(raw)
    if offset_match:
        _, sign, hours_text, minutes_text = offset_match.groups()
        hours = int(hours_text)
        minutes = int(minutes_text or 0)
        if hours > 14 or minutes > 59 or (hours == 14 and minutes > 0):
            raise TimeInputError(
                "Смещение часового пояса должно быть в диапазоне от UTC-14:00 до UTC+14:00."
            )

        total_minutes = hours * 60 + minutes
        if sign == "-":
            total_minutes = -total_minutes

        offset = timezone(timedelta(minutes=total_minutes))
        if total_minutes == 0:
            return "UTC", offset

        canonical = f"UTC{sign}{hours:02d}:{minutes:02d}"
        return canonical, offset

    try:
        zone = ZoneInfo(raw)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise TimeInputError(
            "Неизвестный часовой пояс. Используйте IANA-название вроде "
            "Europe/Moscow или смещение UTC+3."
        ) from exc

    return raw, zone


def parse_time_value(time_text: str) -> time_type:
    for time_format in _TIME_FORMATS:
        try:
            return datetime.strptime(time_text.strip(), time_format).time()
        except ValueError:
            continue

    raise TimeInputError(
        "Не удалось прочитать время. Используйте формат ЧЧ:ММ, например 20:30."
    )


def combine_date_time(
    date_value: date_type,
    time_value: time_type,
    timezone_text: str,
) -> int:
    timezone_name, zone = parse_timezone(timezone_text)
    naive = datetime.combine(date_value, time_value)
    aware = naive.replace(tzinfo=zone)

    # ZoneInfo happily assigns a non-existent local time during a DST gap.
    # Detect it with a UTC round-trip.
    round_trip = aware.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
    if round_trip != naive:
        raise TimeInputError(
            f"В часовом поясе {timezone_name} такого времени не существует "
            "из-за перехода на летнее/зимнее время."
        )

    return int(aware.timestamp())


def parse_start_at(date_text: str, time_text: str, timezone_text: str) -> int:
    """Parse DD.MM.YYYY + HH:MM in a timezone and return a Unix timestamp."""

    parsed_date = None
    for date_format in _DATE_FORMATS:
        try:
            parsed_date = datetime.strptime(date_text.strip(), date_format).date()
            break
        except ValueError:
            continue

    if parsed_date is None:
        raise TimeInputError(
            "Не удалось прочитать дату. Используйте формат ДД.ММ.ГГГГ, "
            "например 26.10.2026."
        )

    return combine_date_time(
        parsed_date, parse_time_value(time_text), timezone_text
    )


def format_timestamp(timestamp: int, style: str = "F") -> str:
    """Discord timestamp markup. Discord renders it in every viewer's timezone."""

    return f"<t:{int(timestamp)}:{style}>"
