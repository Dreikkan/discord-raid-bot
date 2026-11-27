from __future__ import annotations

import copy
import json
import logging
import re
import uuid
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from .constants import (
    MAX_REMINDER_DELETE_MINUTES,
    MAX_REMINDER_DESCRIPTION_LENGTH,
    WEEKDAY_LABELS,
)
from .time_utils import (
    TimeInputError,
    combine_date_time,
    next_daily_event,
    next_weekly_event,
    parse_time_value,
    parse_timezone,
)

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ACTIVITIES_PATH = PROJECT_ROOT / "config" / "activities.json"

_WEEKDAY_ALIASES: dict[str, int] = {}
for _index, _label in enumerate(WEEKDAY_LABELS):
    _WEEKDAY_ALIASES[_label.casefold()] = _index
for _aliases, _index in (
    (("пн",), 0),
    (("вт",), 1),
    (("ср",), 2),
    (("чт",), 3),
    (("пт",), 4),
    (("сб",), 5),
    (("вс",), 6),
):
    for _alias in _aliases:
        _WEEKDAY_ALIASES[_alias] = _index

_DAILY_ALIASES = {"ежедневно", "каждый день", "daily"}
_SCHEDULE_RE = re.compile(
    r"^(?P<day>.+?)\s+"
    r"(?P<start>\d{1,2}[:.]\d{2})\s*[-–—]\s*"
    r"(?P<end>\d{1,2}[:.]\d{2})$"
)


class ActivityError(ValueError):
    """Raised for invalid activity schedules or settings."""


def _normalize_day(value: str) -> int | None:
    normalized = value.strip().casefold().replace("ё", "е").rstrip(".")
    if normalized in _DAILY_ALIASES:
        return None
    if normalized in _WEEKDAY_ALIASES:
        return _WEEKDAY_ALIASES[normalized]
    raise ActivityError(
        f"Неизвестный день недели: «{value}». Используйте, например, "
        "«Вторник» или «Ежедневно»."
    )


def _normalize_time(value: str) -> str:
    return parse_time_value(value).strftime("%H:%M")


def normalize_schedule(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ActivityError("Расписание должно быть объектом.")

    weekday_raw = raw.get("weekday")
    weekday: int | None
    if weekday_raw is None:
        weekday = None
    else:
        try:
            weekday = int(weekday_raw)
        except (TypeError, ValueError) as exc:
            raise ActivityError("Некорректный день недели в расписании.") from exc
        if not 0 <= weekday <= 6:
            raise ActivityError("День недели должен быть от 0 до 6.")

    try:
        start = _normalize_time(str(raw.get("start", "")))
        end = _normalize_time(str(raw.get("end", "")))
    except TimeInputError as exc:
        raise ActivityError(str(exc)) from exc

    return {"weekday": weekday, "start": start, "end": end}


def parse_schedules(value: str) -> list[dict[str, Any]]:
    """Parse strings like ``Вторник 20:00-22:00; Суббота 19:00-21:00``."""

    parts = [
        part.strip()
        for part in re.split(r"[;\n|]+", value)
        if part.strip()
    ]
    if not parts:
        raise ActivityError("Укажите хотя бы одно расписание.")

    schedules: list[dict[str, Any]] = []
    seen: set[tuple[int | None, str, str]] = set()

    for part in parts:
        match = _SCHEDULE_RE.fullmatch(part)
        if match is None:
            raise ActivityError(
                "Не удалось прочитать расписание "
                f"«{part}». Формат: `Вторник 20:00-22:00`."
            )

        weekday = _normalize_day(match.group("day"))
        try:
            start = _normalize_time(match.group("start"))
            end = _normalize_time(match.group("end"))
        except TimeInputError as exc:
            raise ActivityError(str(exc)) from exc

        key = (weekday, start, end)
        if key in seen:
            continue
        seen.add(key)
        schedules.append({"weekday": weekday, "start": start, "end": end})

    if not schedules:
        raise ActivityError("Укажите хотя бы одно расписание.")
    return schedules


def format_schedule(schedule: dict[str, Any]) -> str:
    weekday = schedule.get("weekday")
    day = (
        "Ежедневно"
        if weekday is None
        else WEEKDAY_LABELS[int(weekday)]
    )
    return f"{day}, {schedule['start']}–{schedule['end']}"


def format_schedules(schedules: list[dict[str, Any]]) -> str:
    return "; ".join(format_schedule(schedule) for schedule in schedules)


def normalize_activity(
    raw: dict[str, Any], *, default_id: str | None = None
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ActivityError("Активность должна быть объектом.")

    name = str(raw.get("name", "")).strip()
    if not name:
        raise ActivityError("Название активности не может быть пустым.")
    if len(name) > 100:
        raise ActivityError("Название активности слишком длинное.")

    activity_id = str(raw.get("id") or default_id or uuid.uuid4().hex[:10]).strip()
    if not activity_id:
        activity_id = uuid.uuid4().hex[:10]

    description = str(raw.get("description", "")).strip()
    if len(description) > MAX_REMINDER_DESCRIPTION_LENGTH:
        raise ActivityError(
            "Описание слишком длинное: максимум "
            f"{MAX_REMINDER_DESCRIPTION_LENGTH} символов."
        )

    channel_id = raw.get("channel_id")
    role_id = raw.get("role_id")
    try:
        channel_id = int(channel_id) if channel_id is not None else None
        role_id = int(role_id) if role_id is not None else None
    except (TypeError, ValueError) as exc:
        raise ActivityError("Некорректный канал или роль активности.") from exc

    try:
        delete_after_minutes = int(
            raw.get("delete_after_minutes", 60)
        )
    except (TypeError, ValueError) as exc:
        raise ActivityError("Некорректное время автоудаления.") from exc
    if not 1 <= delete_after_minutes <= MAX_REMINDER_DELETE_MINUTES:
        raise ActivityError(
            "Время автоудаления должно быть от 1 до "
            f"{MAX_REMINDER_DELETE_MINUTES} минут."
        )

    raw_schedules = raw.get("schedules", [])
    if not isinstance(raw_schedules, list):
        raise ActivityError("Расписания активности должны быть списком.")
    schedules: list[dict[str, Any]] = []
    seen: set[tuple[int | None, str, str]] = set()
    for raw_schedule in raw_schedules:
        schedule = normalize_schedule(raw_schedule)
        key = (
            schedule["weekday"],
            schedule["start"],
            schedule["end"],
        )
        if key not in seen:
            seen.add(key)
            schedules.append(schedule)

    try:
        last_sent_event_at = int(raw.get("last_sent_event_at", 0))
    except (TypeError, ValueError):
        last_sent_event_at = 0

    return {
        "id": activity_id,
        "name": name,
        "description": description,
        "channel_id": channel_id,
        "role_id": role_id,
        "delete_after_minutes": delete_after_minutes,
        "schedules": schedules,
        "last_sent_event_at": last_sent_event_at,
    }


@lru_cache(maxsize=1)
def _load_defaults() -> tuple[dict[str, Any], ...]:
    if not ACTIVITIES_PATH.is_file():
        return ()

    try:
        with ACTIVITIES_PATH.open("r", encoding="utf-8-sig") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError):
        log.exception("Не удалось прочитать config/activities.json")
        return ()

    raw_activities = (
        payload.get("activities")
        if isinstance(payload, dict)
        else payload
    )
    if not isinstance(raw_activities, list):
        log.error("config/activities.json имеет неверный формат")
        return ()

    activities: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for raw in raw_activities:
        try:
            activity = normalize_activity(raw)
        except ActivityError:
            log.exception("Пропущена некорректная активность в конфиге: %r", raw)
            continue
        if activity["name"].casefold() in seen_names:
            log.warning("Дубликат активности в конфиге: %s", activity["name"])
            continue
        seen_names.add(activity["name"].casefold())
        activity["channel_id"] = None
        activity["role_id"] = None
        activity["last_sent_event_at"] = 0
        activities.append(activity)
    return tuple(activities)


def activity_defaults() -> list[dict[str, Any]]:
    return copy.deepcopy(list(_load_defaults()))


def next_activity_occurrence(
    activity: dict[str, Any],
    timezone_text: str,
    *,
    after_ts: int,
) -> tuple[int, dict[str, Any]] | None:
    best: tuple[int, dict[str, Any]] | None = None

    for schedule in activity.get("schedules", []):
        try:
            time_value = parse_time_value(str(schedule["start"]))
            if schedule.get("weekday") is None:
                event_at = next_daily_event(
                    time_value, timezone_text, after_ts=after_ts
                )
            else:
                event_at = next_weekly_event(
                    int(schedule["weekday"]),
                    time_value,
                    timezone_text,
                    after_ts=after_ts,
                )
        except (KeyError, TypeError, ValueError, TimeInputError):
            continue

        if best is None or event_at < best[0]:
            best = (event_at, schedule)

    return best


def activity_end_at(
    schedule: dict[str, Any],
    timezone_text: str,
    start_at: int,
) -> int:
    _, zone = parse_timezone(timezone_text)
    local_start = datetime.fromtimestamp(start_at, tz=zone)
    start_time = parse_time_value(str(schedule["start"]))
    end_time = parse_time_value(str(schedule["end"]))

    end_date = local_start.date()
    if end_time <= start_time:
        end_date = end_date + timedelta(days=1)

    try:
        return combine_date_time(end_date, end_time, timezone_text)
    except TimeInputError:
        return start_at
