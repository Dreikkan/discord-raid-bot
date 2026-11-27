from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from .activities import ActivityError, activity_defaults, normalize_activity
from .catalog import bundled_catalog
from .constants import (
    DEFAULT_LIMITS,
    DEFAULT_ROLE_EMOJIS,
    DEFAULT_TIMEZONE,
    DEFAULT_TITLE,
    MAX_TITLE_LENGTH,
    ROLE_ORDER,
    STATUS_ABSENT,
    STATUS_BENCH,
    STATUS_MAIN,
)
from .gacha import (
    GACHA_POOL_VERSION,
    GachaError,
    LEGACY_PLACEHOLDER_IDS,
    gacha_item_defaults,
    normalize_item,
    normalize_items,
)

_STORE_VERSION = 2
_SETTINGS_VERSION = 3


def default_settings() -> dict[str, Any]:
    return {
        "settings_version": _SETTINGS_VERSION,
        "title": DEFAULT_TITLE,
        "limits": dict(DEFAULT_LIMITS),
        "role_emojis": dict(DEFAULT_ROLE_EMOJIS),
        "timezone": DEFAULT_TIMEZONE,
        "specs": bundled_catalog(),
        "activities": activity_defaults(),
        "gacha_items": gacha_item_defaults(),
        "gacha_pool_version": GACHA_POOL_VERSION,
    }


def _empty_store() -> dict[str, Any]:
    return {
        "version": _STORE_VERSION,
        "guilds": {},
        "raids": {},
        "profiles": {},
        "activity_events": {},
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
        data.setdefault("profiles", {})
        data.setdefault("activity_events", {})
        data.setdefault("scheduled_deletions", [])
        if (
            not isinstance(data["guilds"], dict)
            or not isinstance(data["raids"], dict)
            or not isinstance(data["profiles"], dict)
            or not isinstance(data["activity_events"], dict)
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
    def _normalize_activities(raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            return activity_defaults()

        activities: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        seen_ids: set[str] = set()

        for item in raw:
            try:
                activity = normalize_activity(item)
            except ActivityError:
                continue

            if activity["name"].casefold() in seen_names:
                continue
            if activity["id"] in seen_ids:
                continue

            seen_names.add(activity["name"].casefold())
            seen_ids.add(activity["id"])
            activities.append(activity)

        return activities

    @staticmethod
    def _migrate_gacha_items(
        existing: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Replace the old placeholder pool while keeping custom items."""

        items = [
            item
            for item in existing
            if item["id"] not in LEGACY_PLACEHOLDER_IDS
            or item.get("image")
            or item.get("image_url")
            or item.get("announce")
        ]
        seen_ids = {item["id"] for item in items}
        seen_names = {item["name"].casefold() for item in items}
        defaults = gacha_item_defaults()
        for item in defaults:
            if item["id"] in seen_ids:
                continue
            if item["name"].casefold() in seen_names:
                continue
            items.append(item)
            seen_ids.add(item["id"])
            seen_names.add(item["name"].casefold())

        # Keep the legendary weights of the shipped pool in sync with the
        # current drop rates (the core is pinned to a 0.1% base chance).
        legendary_weights = {
            item["id"]: item["weight"]
            for item in defaults
            if item["rarity"] == "legendary"
        }
        for item in items:
            if item["id"] in legendary_weights:
                item["weight"] = legendary_weights[item["id"]]
        return items

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

        settings["activities"] = Store._normalize_activities(
            raw.get("activities")
        )

        try:
            pool_version = int(raw.get("gacha_pool_version", 1))
        except (TypeError, ValueError):
            pool_version = 1

        raw_gacha_items = raw.get("gacha_items")
        if isinstance(raw_gacha_items, list):
            gacha_items = normalize_items(raw_gacha_items)
            if pool_version < GACHA_POOL_VERSION:
                gacha_items = Store._migrate_gacha_items(gacha_items)
            settings["gacha_items"] = gacha_items
        else:
            settings["gacha_items"] = gacha_item_defaults()
        settings["gacha_pool_version"] = GACHA_POOL_VERSION
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

    def find_activity(
        self, guild_id: str | int, name: str
    ) -> dict[str, Any] | None:
        folded = name.strip().casefold()
        for activity in self.settings_for(guild_id).get("activities", []):
            if activity["name"].casefold() == folded:
                return activity
        return None

    def save_activity(
        self, guild_id: str | int, activity: dict[str, Any]
    ) -> dict[str, Any]:
        normalized = normalize_activity(activity)
        settings = self.settings_for(guild_id)

        for index, existing in enumerate(settings["activities"]):
            if existing["id"] == normalized["id"]:
                settings["activities"][index] = normalized
                self._save()
                return normalized

        folded = normalized["name"].casefold()
        for existing in settings["activities"]:
            if existing["name"].casefold() == folded:
                raise ActivityError("Активность с таким названием уже существует.")

        settings["activities"].append(normalized)
        self._save()
        return normalized

    def mark_activity_sent(
        self, guild_id: str | int, activity_id: str, event_at: int
    ) -> None:
        settings = self.settings_for(guild_id)
        for activity in settings.get("activities", []):
            if activity["id"] == activity_id:
                activity["last_sent_event_at"] = int(event_at)
                self._save()
                return

    # ----------------------------------------------------- Gacha settings

    def find_gacha_item(
        self, guild_id: str | int, item_id: str
    ) -> dict[str, Any] | None:
        for item in self.settings_for(guild_id).get("gacha_items", []):
            if str(item.get("id")) == str(item_id):
                return item
        return None

    def save_gacha_item(
        self, guild_id: str | int, item: dict[str, Any]
    ) -> dict[str, Any]:
        normalized = normalize_item(item)
        settings = self.settings_for(guild_id)
        items = settings.setdefault("gacha_items", [])

        for index, existing in enumerate(items):
            if str(existing.get("id")) == normalized["id"]:
                for other in items:
                    if (
                        str(other.get("id")) != normalized["id"]
                        and str(other.get("name", "")).casefold()
                        == normalized["name"].casefold()
                    ):
                        raise GachaError(
                            "Предмет с таким названием уже есть в пуле."
                        )
                items[index] = normalized
                self._save()
                return normalized

        for existing in items:
            if (
                str(existing.get("name", "")).casefold()
                == normalized["name"].casefold()
            ):
                raise GachaError("Предмет с таким названием уже есть в пуле.")

        items.append(normalized)
        self._save()
        return normalized

    def delete_gacha_item(self, guild_id: str | int, item_id: str) -> bool:
        settings = self.settings_for(guild_id)
        items = settings.get("gacha_items", [])
        for index, item in enumerate(items):
            if str(item.get("id")) == str(item_id):
                items.pop(index)
                self._save()
                return True
        return False

    # ------------------------------------------------------------ Profiles

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _ensure_profile(
        self, guild_id: str | int, user_id: str | int
    ) -> tuple[dict[str, Any], bool]:
        profiles = self.data.setdefault("profiles", {})
        guild_profiles = profiles.setdefault(str(guild_id), {})
        key = str(user_id)
        raw = guild_profiles.get(key)
        now = int(time.time())
        if not isinstance(raw, dict):
            raw = {}

        inventory: dict[str, int] = {}
        raw_inventory = raw.get("inventory")
        if isinstance(raw_inventory, dict):
            for item_id, count in raw_inventory.items():
                amount = self._safe_int(count, 0)
                if item_id and amount > 0:
                    inventory[str(item_id)] = amount

        role_rewards: list[str] = []
        raw_role_rewards = raw.get("role_rewards")
        if isinstance(raw_role_rewards, list):
            for reward_id in raw_role_rewards:
                value = str(reward_id).strip()
                if value and value not in role_rewards:
                    role_rewards.append(value)

        profile = {
            "balance": max(0, self._safe_int(raw.get("balance"), 0)),
            "inventory": inventory,
            "pity": max(0, self._safe_int(raw.get("pity"), 0)),
            "core_pity": max(0, self._safe_int(raw.get("core_pity"), 0)),
            "total_pulls": max(
                0, self._safe_int(raw.get("total_pulls"), 0)
            ),
            "role_rewards": role_rewards,
            "created_at": max(0, self._safe_int(raw.get("created_at"), now)),
            "updated_at": max(0, self._safe_int(raw.get("updated_at"), now)),
        }
        if isinstance(raw, dict) and profile == raw:
            return raw, False
        guild_profiles[key] = profile
        return profile, True

    def profile_for(
        self, guild_id: str | int, user_id: str | int
    ) -> dict[str, Any]:
        profile, changed = self._ensure_profile(guild_id, user_id)
        if changed:
            self._save()
        return profile

    def add_currency(
        self, guild_id: str | int, user_id: str | int, amount: int
    ) -> dict[str, Any]:
        profile, _ = self._ensure_profile(guild_id, user_id)
        profile["balance"] = max(0, profile["balance"] + int(amount))
        profile["updated_at"] = int(time.time())
        self._save()
        return profile

    def mark_role_reward(
        self,
        guild_id: str | int,
        user_id: str | int,
        reward_id: str,
    ) -> dict[str, Any]:
        profile, _ = self._ensure_profile(guild_id, user_id)
        reward_id = str(reward_id)
        if reward_id not in profile["role_rewards"]:
            profile["role_rewards"].append(reward_id)
            profile["updated_at"] = int(time.time())
            self._save()
        return profile

    def complete_gacha_pull(
        self,
        guild_id: str | int,
        user_id: str | int,
        *,
        cost: int,
        item_ids: list[str],
        pity: int,
        core_pity: int = 0,
    ) -> dict[str, Any]:
        profile, _ = self._ensure_profile(guild_id, user_id)
        cost = int(cost)
        if cost < 0:
            raise ValueError("Стоимость крутки не может быть отрицательной.")
        if profile["balance"] < cost:
            raise ValueError("Недостаточно валюты для крутки.")
        if not item_ids:
            raise ValueError("Нет наград для сохранения.")

        counts: dict[str, int] = {}
        for item_id in item_ids:
            key = str(item_id)
            counts[key] = counts.get(key, 0) + 1

        profile["balance"] -= cost
        for item_id, count in counts.items():
            profile["inventory"][item_id] = (
                profile["inventory"].get(item_id, 0) + count
            )
        profile["pity"] = max(0, int(pity))
        profile["core_pity"] = max(0, int(core_pity))
        profile["total_pulls"] += len(item_ids)
        profile["updated_at"] = int(time.time())
        self._save()
        return profile

    # ---------------------------------------------------- Activity rewards

    def register_activity_event(
        self,
        message_id: str | int,
        *,
        guild_id: str | int,
        activity_id: str,
        start_at: int,
        end_at: int,
    ) -> None:
        events = self.data.setdefault("activity_events", {})
        key = str(message_id)
        existing = events.get(key)
        checkins = (
            list(existing.get("checkins", []))
            if isinstance(existing, dict)
            else []
        )
        events[key] = {
            "guild_id": str(guild_id),
            "activity_id": str(activity_id),
            "start_at": int(start_at),
            "end_at": int(end_at),
            "checkins": checkins,
            "created_at": int(time.time()),
        }
        self._save()

    def activity_event(self, message_id: str | int) -> dict[str, Any] | None:
        event = self.data.get("activity_events", {}).get(str(message_id))
        return event if isinstance(event, dict) else None

    def claim_activity_reward(
        self,
        message_id: str | int,
        user_id: str | int,
        *,
        amount: int,
        now: int | None = None,
    ) -> tuple[str, int, int]:
        event = self.activity_event(message_id)
        if event is None:
            return "missing", 0, 0

        timestamp = int(now) if now is not None else int(time.time())
        profile, _ = self._ensure_profile(
            event.get("guild_id", 0), user_id
        )

        if timestamp > int(event.get("end_at", 0)):
            return "ended", 0, profile["balance"]

        checkins = event.setdefault("checkins", [])
        if not isinstance(checkins, list):
            checkins = []
            event["checkins"] = checkins
        user_key = str(user_id)
        if user_key in checkins:
            return "already", 0, profile["balance"]

        checkins.append(user_key)
        profile["balance"] = max(0, profile["balance"] + int(amount))
        profile["updated_at"] = timestamp
        self._save()
        return "ok", int(amount), profile["balance"]

    def prune_activity_events(self, cutoff: int) -> int:
        events = self.data.get("activity_events", {})
        expired = [
            key
            for key, event in events.items()
            if int(event.get("end_at", 0)) < int(cutoff)
        ]
        for key in expired:
            events.pop(key, None)
        if expired:
            self._save()
        return len(expired)

    # --------------------------------------------------------- Raid rewards

    def award_raid_rewards(
        self,
        raid_id: str,
        *,
        main_amount: int,
        bench_amount: int,
        now: int | None = None,
    ) -> list[dict[str, Any]]:
        raid = self.data["raids"].get(raid_id)
        if raid is None:
            return []

        # Raids created before the economy update do not have this field.
        # Mark them as processed so old raids are not rewarded retroactively.
        if "rewards_awarded_at" not in raid:
            raid["rewards_awarded_at"] = (
                int(now) if now is not None else int(time.time())
            )
            self._save()
            return []

        if raid.get("rewards_awarded_at") is not None:
            return []

        timestamp = int(now) if now is not None else int(time.time())
        awards: list[dict[str, Any]] = []
        for user_id, registration in raid.get("registrations", {}).items():
            status = registration.get("status")
            amount = (
                int(main_amount)
                if status == STATUS_MAIN
                else int(bench_amount)
                if status == STATUS_BENCH
                else 0
            )
            if amount <= 0:
                continue
            profile, _ = self._ensure_profile(raid["guild_id"], user_id)
            profile["balance"] = max(0, profile["balance"] + amount)
            profile["updated_at"] = timestamp
            awards.append(
                {"user_id": str(user_id), "amount": amount, "status": status}
            )

        raid["rewards_awarded_at"] = timestamp
        self._save()
        return awards

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
            "rewards_awarded_at": None,
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
