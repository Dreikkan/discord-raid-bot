from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from .catalog import bundled_catalog
from .constants import (
    DEFAULT_LIMITS,
    DEFAULT_ROLE_EMOJIS,
    DEFAULT_TIMEZONE,
    DEFAULT_TITLE,
    MAX_REMINDER_DELETE_MINUTES,
    MAX_REMINDER_DESCRIPTION_LENGTH,
    MAX_TITLE_LENGTH,
    ROLE_ORDER,
    STATUS_ABSENT,
    STATUS_BENCH,
    STATUS_MAIN,
)
from .time_utils import TimeInputError, parse_time_value, parse_timezone

_STORE_VERSION = 1
_SETTINGS_VERSION = 2


def default_settings() -> dict[str, Any]:
    return {
        "settings_version": _SETTINGS_VERSION,
        "title": DEFAULT_TITLE,
        "limits": dict(DEFAULT_LIMITS),
        "role_emojis": dict(DEFAULT_ROLE_EMOJIS),
        "timezone": DEFAULT_TIMEZONE,
        "specs": bundled_catalog(),
        "reminder": None,
    }


def _empty_store() -> dict[str, Any]:
    return {
        "version": _STORE_VERSION,
        "guilds": {},
        "raids": {},
        "scheduled_deletions": [],
    }


class Store:
    """Small JSON-backed store. The bot is single-process, so sync writes are fine."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.data = self._load()
        if not self.path.exists():
            self._save()

    # ------------------------------------------------------------------ I/O

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return _empty_store()

        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Не удалось прочитать файл данных {self.path}. "
                "Исправьте или удалите его."
            ) from exc

        if not isinstance(data, dict):
            raise RuntimeError(f"Файл данных {self.path} имеет неверный формат.")

        data.setdefault("version", _STORE_VERSION)
        data.setdefault("guilds", {})
        data.setdefault("raids", {})
        data.setdefault("scheduled_deletions", [])
        if (
            not isinstance(data["guilds"], dict)
            or not isinstance(data["raids"], dict)
            or not isinstance(data["scheduled_deletions"], list)
        ):
            raise RuntimeError(f"Файл данных {self.path} имеет неверный формат.")
        return data

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.tmp")

        with temporary.open("w", encoding="utf-8", newline="\n") as file:
            json.dump(self.data, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())

        os.replace(temporary, self.path)

    def save(self) -> None:
        self._save()

    # ------------------------------------------------------------- Settings

    @staticmethod
    def _normalize_reminder(raw: Any) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            return None

        frequency = str(raw.get("frequency", "")).strip()
        if frequency not in {"daily", "weekly"}:
            return None

        try:
            channel_id = int(raw["channel_id"])
            role_id = int(raw["role_id"])
            delete_after_minutes = int(raw["delete_after_minutes"])
            next_event_at = int(raw["next_event_at"])
            next_fire_at = int(raw["next_fire_at"])
            time_value = parse_time_value(str(raw.get("time", "")))
            timezone = parse_timezone(str(raw.get("timezone", "")))[0]
        except (KeyError, TypeError, ValueError, TimeInputError):
            return None

        if not 1 <= delete_after_minutes <= MAX_REMINDER_DELETE_MINUTES:
            return None
        if next_event_at <= 0 or next_fire_at <= 0:
            return None

        weekday = None
        if frequency == "weekly":
            try:
                weekday = int(raw["weekday"])
            except (KeyError, TypeError, ValueError):
                return None
            if not 0 <= weekday <= 6:
                return None

        description = str(raw.get("description", "")).strip()
        if len(description) > MAX_REMINDER_DESCRIPTION_LENGTH:
            description = description[:MAX_REMINDER_DESCRIPTION_LENGTH]

        return {
            "frequency": frequency,
            "weekday": weekday,
            "time": time_value.strftime("%H:%M"),
            "timezone": timezone,
            "channel_id": channel_id,
            "delete_after_minutes": delete_after_minutes,
            "role_id": role_id,
            "description": description,
            "next_event_at": next_event_at,
            "next_fire_at": next_fire_at,
        }

    @staticmethod
    def _normalize_settings(raw: Any) -> dict[str, Any]:
        settings = default_settings()
        if not isinstance(raw, dict):
            return settings

        title = raw.get("title")
        if isinstance(title, str) and title.strip():
            settings["title"] = title.strip()[:MAX_TITLE_LENGTH]

        try:
            settings_version = int(raw.get("settings_version", 1))
        except (TypeError, ValueError):
            settings_version = 1

        # Version 2 switches old persisted limits (2/3/8) to 1/2/7 once.
        limits = raw.get("limits")
        if settings_version >= 2 and isinstance(limits, dict):
            for role in ROLE_ORDER:
                try:
                    value = int(limits.get(role, DEFAULT_LIMITS[role]))
                except (TypeError, ValueError):
                    value = DEFAULT_LIMITS[role]
                settings["limits"][role] = max(1, min(value, 50))

        timezone = raw.get("timezone")
        if isinstance(timezone, str) and timezone.strip():
            settings["timezone"] = timezone.strip()

        settings["reminder"] = Store._normalize_reminder(raw.get("reminder"))
        return settings

    def settings_for(self, guild_id: str | int) -> dict[str, Any]:
        guild_key = str(guild_id)
        raw = self.data["guilds"].get(guild_key)
        normalized = self._normalize_settings(raw)
        if raw != normalized:
            self.data["guilds"][guild_key] = normalized
            self._save()
        return self.data["guilds"][guild_key]

    def set_title(self, guild_id: str | int, title: str) -> None:
        settings = self.settings_for(guild_id)
        settings["title"] = title.strip()[:MAX_TITLE_LENGTH]
        self._save()

    def set_limits(self, guild_id: str | int, limits: dict[str, int]) -> None:
        settings = self.settings_for(guild_id)
        for role in ROLE_ORDER:
            settings["limits"][role] = max(1, min(int(limits[role]), 50))
        self._save()

    def set_timezone(self, guild_id: str | int, timezone: str) -> None:
        settings = self.settings_for(guild_id)
        settings["timezone"] = timezone
        self._save()

    def set_reminder_config(
        self, guild_id: str | int, reminder: dict[str, Any]
    ) -> dict[str, Any]:
        normalized = self._normalize_reminder(reminder)
        if normalized is None:
            raise ValueError("Некорректные настройки напоминания.")

        settings = self.settings_for(guild_id)
        settings["reminder"] = normalized
        self._save()
        return normalized

    def disable_reminder(self, guild_id: str | int) -> None:
        settings = self.settings_for(guild_id)
        settings["reminder"] = None
        self._save()

    def advance_reminder(
        self,
        guild_id: str | int,
        *,
        next_event_at: int,
        next_fire_at: int,
    ) -> None:
        settings = self.settings_for(guild_id)
        reminder = settings.get("reminder")
        if not isinstance(reminder, dict):
            return
        reminder["next_event_at"] = int(next_event_at)
        reminder["next_fire_at"] = int(next_fire_at)
        self._save()

    # ------------------------------------------------------- Auto-deletions

    def schedule_message_deletion(
        self,
        *,
        channel_id: str | int,
        message_id: str | int,
        delete_at: int,
    ) -> None:
        deletions = self.data.setdefault("scheduled_deletions", [])
        deletions.append(
            {
                "channel_id": str(channel_id),
                "message_id": str(message_id),
                "delete_at": int(delete_at),
            }
        )
        self._save()

    def pop_due_deletions(self, now: int) -> list[dict[str, Any]]:
        deletions = self.data.get("scheduled_deletions", [])
        due = [
            item
            for item in deletions
            if int(item.get("delete_at", 0)) <= now
        ]
        if due:
            self.data["scheduled_deletions"] = [
                item for item in deletions if item not in due
            ]
            self._save()
        return due

    def specs_for_role(self, guild_id: str | int, role: str) -> list[dict[str, Any]]:
        return [
            spec
            for spec in self.settings_for(guild_id)["specs"]
            if spec["role"] == role
        ]

    # --------------------------------------------------------------- Raids

    def create_raid(
        self,
        *,
        guild_id: str | int,
        channel_id: str | int,
        created_by: str | int,
        title: str,
        description: str,
        start_at: int,
        limits: dict[str, int],
        role_emojis: dict[str, str],
    ) -> dict[str, Any]:
        raid_id = uuid.uuid4().hex[:12]
        while raid_id in self.data["raids"]:
            raid_id = uuid.uuid4().hex[:12]

        now = int(time.time())
        raid = {
            "id": raid_id,
            "guild_id": str(guild_id),
            "channel_id": str(channel_id),
            "message_id": None,
            "created_by": str(created_by),
            "title": title,
            "description": description,
            "start_at": int(start_at),
            "limits": {role: int(limits[role]) for role in ROLE_ORDER},
            "role_emojis": {role: str(role_emojis[role]) for role in ROLE_ORDER},
            "registrations": {},
            "created_at": now,
            "notification_sent_at": None,
        }
        self.data["raids"][raid_id] = raid
        self._save()
        return raid

    def set_raid_message(
        self, raid_id: str, *, channel_id: str | int, message_id: str | int
    ) -> None:
        raid = self.data["raids"].get(raid_id)
        if raid is None:
            return
        raid["channel_id"] = str(channel_id)
        raid["message_id"] = str(message_id)
        self._save()

    def get_raid(self, raid_id: str) -> dict[str, Any] | None:
        return self.data["raids"].get(raid_id)

    def all_raids(self) -> list[dict[str, Any]]:
        return list(self.data["raids"].values())

    def set_registration(
        self,
        raid_id: str,
        user_id: str | int,
        *,
        role: str,
        specializations: list[dict[str, str]],
        display_name: str,
        status: str,
    ) -> None:
        raid = self.data["raids"][raid_id]
        clean_specs = [
            {
                "id": str(spec["id"]),
                "name": str(spec["name"]),
                "emoji": str(spec.get("emoji") or ""),
            }
            for spec in specializations
        ]
        raid["registrations"][str(user_id)] = {
            "role": role,
            "specializations": clean_specs,
            "display_name": display_name,
            "status": status,
            "updated_at": int(time.time()),
        }
        self._save()

    def remove_registration(self, raid_id: str, user_id: str | int) -> bool:
        raid = self.data["raids"].get(raid_id)
        if raid is None:
            return False
        removed = raid["registrations"].pop(str(user_id), None)
        if removed is None:
            return False
        self._save()
        return True

    def mark_notification_sent(self, raid_id: str, timestamp: int | None = None) -> None:
        raid = self.data["raids"].get(raid_id)
        if raid is None:
            return
        raid["notification_sent_at"] = int(timestamp or time.time())
        self._save()

    def delete_raid(self, raid_id: str) -> None:
        if self.data["raids"].pop(raid_id, None) is not None:
            self._save()

    # ----------------------------------------------------------- Convenience

    @staticmethod
    def statuses(raid: dict[str, Any], status: str) -> list[tuple[str, dict[str, Any]]]:
        return [
            (user_id, registration)
            for user_id, registration in raid.get("registrations", {}).items()
            if registration.get("status") == status
        ]

    @staticmethod
    def main_by_role(raid: dict[str, Any], role: str) -> list[tuple[str, dict[str, Any]]]:
        return [
            (user_id, registration)
            for user_id, registration in raid.get("registrations", {}).items()
            if registration.get("status") == STATUS_MAIN
            and registration.get("role") == role
        ]

    @staticmethod
    def bench(raid: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        return Store.statuses(raid, STATUS_BENCH)

    @staticmethod
    def absent(raid: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        return Store.statuses(raid, STATUS_ABSENT)
