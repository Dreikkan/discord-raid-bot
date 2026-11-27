from __future__ import annotations

import copy
import json
import logging
import random
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence

from .constants import (
    GACHA_PITY,
    MAX_GACHA_IMAGE_URL_LENGTH,
    MAX_GACHA_ITEM_DESCRIPTION_LENGTH,
    MAX_GACHA_ITEM_NAME_LENGTH,
    MAX_GACHA_ITEM_WEIGHT,
)

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GACHA_ITEMS_PATH = PROJECT_ROOT / "config" / "gacha_items.json"
GACHA_ASSETS_DIR = PROJECT_ROOT / "assets" / "gacha"
GACHA_POOL_VERSION = 3

LEGACY_PLACEHOLDER_IDS: frozenset[str] = frozenset(
    {
        "smoldering-coal",
        "stone-shard",
        "rusty-coin",
        "herb-bundle",
        "flint",
        "old-map",
        "glass-marble",
        "bird-feather",
        "amber-piece",
        "copper-key",
        "clay-figurine",
        "dry-leaf",
        "ribbon-scrap",
        "stone-acorn",
        "dusty-scroll",
        "moonstone",
        "silver-leaf",
        "dew-crystal",
        "obsidian-arrow",
        "griffin-feather",
        "ether-flask",
        "wanderer-ring",
        "mirror-scale",
        "emerald-spark",
        "wind-cloak",
        "bone-amulet",
        "crystal-bell",
        "sapphire-tear",
        "phoenix-flame",
        "siren-tear",
        "dragon-fang",
        "book-of-shadows",
        "heart-of-forest",
        "stardust",
        "thorn-crown",
        "phoenix-ash",
        "ice-rose",
        "voice-of-abyss",
        "eye-of-storm",
        "void-mantle",
        "titan-blood",
        "eternity-clock",
        "storm-heart",
    }
)

RARITY_ORDER: tuple[str, ...] = (
    "common",
    "uncommon",
    "rare",
    "epic",
    "legendary",
)
RARITY_LABELS: dict[str, str] = {
    "common": "Обычная",
    "uncommon": "Необычная",
    "rare": "Редкая",
    "epic": "Эпическая",
    "legendary": "Легендарная",
}
RARITY_EMOJIS: dict[str, str] = {
    "common": "⚪",
    "uncommon": "🟢",
    "rare": "🔵",
    "epic": "🟣",
    "legendary": "🌟",
}
RARITY_COLORS: dict[str, int] = {
    "common": 0x95A5A6,
    "uncommon": 0x2ECC71,
    "rare": 0x3498DB,
    "epic": 0x9B59B6,
    "legendary": 0xF1C40F,
}
RARITY_WEIGHTS: dict[str, int] = {
    "common": 500,
    "uncommon": 260,
    "rare": 130,
    "epic": 90,
    # 2% for all legendary items. The core has 24/96 of this bucket,
    # so its base chance is exactly 0.5%.
    "legendary": 20,
}

_RARITY_ALIASES: dict[str, str] = {
    "common": "common",
    "обычная": "common",
    "обычный": "common",
    "обычное": "common",
    "uncommon": "uncommon",
    "необычная": "uncommon",
    "необычный": "uncommon",
    "необычное": "uncommon",
    "rare": "rare",
    "редкая": "rare",
    "редкий": "rare",
    "редкое": "rare",
    "epic": "epic",
    "эпическая": "epic",
    "эпический": "epic",
    "эпическое": "epic",
    "legendary": "legendary",
    "легендарная": "legendary",
    "легендарный": "legendary",
    "легендарное": "legendary",
}

_RNG = random.SystemRandom()


class GachaError(ValueError):
    """Raised for invalid gacha items or rolls."""


@dataclass(frozen=True)
class RollResult:
    item: dict[str, Any]
    pity: bool = False


def parse_rarity(value: str) -> str:
    normalized = str(value or "").strip().casefold()
    rarity = _RARITY_ALIASES.get(normalized)
    if rarity is None:
        raise GachaError(
            "Редкость должна быть одной из: обычная, необычная, редкая, "
            "эпическая или легендарная."
        )
    return rarity


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "да", "вкл"}
    return bool(value)


def _valid_item_id(value: str) -> bool:
    return bool(value) and all(
        character.isalnum() or character in {"-", "_"} for character in value
    )


def normalize_item(
    raw: dict[str, Any], *, default_id: str | None = None
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise GachaError("Предмет должен быть объектом.")

    item_id = str(raw.get("id") or default_id or uuid.uuid4().hex[:12]).strip()
    if not _valid_item_id(item_id):
        raise GachaError(
            "ID предмета может содержать только буквы, цифры, дефисы и подчёркивания."
        )

    name = str(raw.get("name", "")).strip()
    if not name:
        raise GachaError("Название предмета не может быть пустым.")
    if len(name) > MAX_GACHA_ITEM_NAME_LENGTH:
        raise GachaError(
            f"Название предмета длиннее {MAX_GACHA_ITEM_NAME_LENGTH} символов."
        )

    description = str(raw.get("description", "")).strip()
    if len(description) > MAX_GACHA_ITEM_DESCRIPTION_LENGTH:
        raise GachaError(
            "Описание предмета длиннее "
            f"{MAX_GACHA_ITEM_DESCRIPTION_LENGTH} символов."
        )

    rarity = parse_rarity(str(raw.get("rarity", "common")))

    try:
        weight = int(raw.get("weight", 100))
    except (TypeError, ValueError) as exc:
        raise GachaError("Вес предмета должен быть целым числом.") from exc
    if not 1 <= weight <= MAX_GACHA_ITEM_WEIGHT:
        raise GachaError(
            f"Вес предмета должен быть от 1 до {MAX_GACHA_ITEM_WEIGHT}."
        )

    image = str(raw.get("image") or "").strip()
    if image:
        if Path(image).name != image:
            raise GachaError("Имя файла картинки не должно содержать путь.")
        if not _valid_image_name(image):
            raise GachaError(
                "Имя файла картинки может содержать только буквы, цифры, "
                "дефисы, подчёркивания и точку."
            )

    image_url = str(raw.get("image_url") or "").strip()
    if image_url:
        if not image_url.startswith(("http://", "https://")):
            raise GachaError("Ссылка на картинку должна начинаться с http:// или https://.")
        if len(image_url) > MAX_GACHA_IMAGE_URL_LENGTH:
            raise GachaError("Ссылка на картинку слишком длинная.")

    return {
        "id": item_id,
        "name": name,
        "description": description,
        "rarity": rarity,
        "weight": weight,
        "image": image,
        "image_url": image_url,
        "announce": _as_bool(raw.get("announce", False)),
    }


def _valid_image_name(value: str) -> bool:
    return all(character.isalnum() or character in {"-", "_", "."} for character in value)


@lru_cache(maxsize=1)
def _load_default_items() -> tuple[dict[str, Any], ...]:
    if not GACHA_ITEMS_PATH.is_file():
        log.error("Файл пула гачи не найден: %s", GACHA_ITEMS_PATH)
        return ()

    try:
        with GACHA_ITEMS_PATH.open("r", encoding="utf-8-sig") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError):
        log.exception("Не удалось прочитать config/gacha_items.json")
        return ()

    raw_items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(raw_items, list):
        log.error("config/gacha_items.json имеет неверный формат")
        return ()

    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for raw in raw_items:
        try:
            item = normalize_item(raw)
        except GachaError:
            log.exception("Пропущен некорректный предмет в конфиге: %r", raw)
            continue
        if item["id"] in seen_ids or item["name"].casefold() in seen_names:
            log.warning("Дубликат предмета в конфиге: %s", item["name"])
            continue
        seen_ids.add(item["id"])
        seen_names.add(item["name"].casefold())
        items.append(item)
    return tuple(items)


def gacha_item_defaults() -> list[dict[str, Any]]:
    return copy.deepcopy(list(_load_default_items()))


def normalize_items(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for entry in raw:
        try:
            item = normalize_item(entry)
        except GachaError:
            continue
        if item["id"] in seen_ids or item["name"].casefold() in seen_names:
            continue
        seen_ids.add(item["id"])
        seen_names.add(item["name"].casefold())
        items.append(item)
    return items


def image_path(item: dict[str, Any]) -> Path | None:
    image = str(item.get("image") or "").strip()
    if not image:
        return None
    path = (GACHA_ASSETS_DIR / image).resolve()
    try:
        path.relative_to(GACHA_ASSETS_DIR.resolve())
    except ValueError:
        return None
    return path if path.is_file() else None


def image_reference(item: dict[str, Any]) -> tuple[str | None, Path | None]:
    """Return (embed image URL, local file path) for an item."""

    path = image_path(item)
    if path is not None:
        return f"attachment://{path.name}", path

    image_url = str(item.get("image_url") or "").strip()
    if image_url:
        return image_url, None
    return None, None


def _pick_weighted(items: Sequence[dict[str, Any]], rng: Any) -> dict[str, Any]:
    weights = [max(1, int(item.get("weight", 100))) for item in items]
    return rng.choices(list(items), weights=weights, k=1)[0]


def _pick_rarity(items: Sequence[dict[str, Any]], rng: Any) -> str:
    available = [
        rarity
        for rarity in RARITY_ORDER
        if any(item.get("rarity") == rarity for item in items)
    ]
    weights = [RARITY_WEIGHTS[rarity] for rarity in available]
    return rng.choices(available, weights=weights, k=1)[0]


def roll_gacha(
    items: Sequence[dict[str, Any]],
    count: int,
    pity: int,
    *,
    rng: Any | None = None,
) -> tuple[list[RollResult], int]:
    if count < 1:
        raise GachaError("Количество круток должно быть положительным.")
    pool = [item for item in items if isinstance(item, dict)]
    if not pool:
        raise GachaError("Пул наград пуст. Администратор должен добавить предметы.")

    random_source = rng or _RNG
    current_pity = max(0, int(pity))
    results: list[RollResult] = []

    for _ in range(count):
        if current_pity + 1 >= GACHA_PITY:
            legendary = [
                item for item in pool if item.get("rarity") == "legendary"
            ]
            if legendary:
                item = _pick_weighted(legendary, random_source)
                results.append(RollResult(item=item, pity=True))
                current_pity = 0
                continue

        rarity = _pick_rarity(pool, random_source)
        candidates = [
            item for item in pool if item.get("rarity") == rarity
        ] or pool
        item = _pick_weighted(candidates, random_source)
        results.append(RollResult(item=item))
        if item.get("rarity") == "legendary":
            current_pity = 0
        else:
            current_pity += 1

    return results, current_pity


def rarity_summary(results: Iterable[RollResult]) -> str:
    counts: dict[str, int] = {}
    for result in results:
        rarity = str(result.item.get("rarity") or "common")
        counts[rarity] = counts.get(rarity, 0) + 1
    parts = [
        f"{RARITY_EMOJIS[rarity]}×{counts[rarity]}"
        for rarity in RARITY_ORDER
        if counts.get(rarity)
    ]
    return " ".join(parts) or "—"
