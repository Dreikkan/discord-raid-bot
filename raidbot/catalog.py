from __future__ import annotations

import copy
import json
import logging
from functools import lru_cache
from pathlib import Path

from .constants import MAX_SPEC_NAME_LENGTH
from .specs import normalize_role

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = PROJECT_ROOT / "assets" / "spec_icons" / "catalog.json"


@lru_cache(maxsize=1)
def _load_catalog() -> tuple[int, tuple[dict[str, str], ...]]:
    if not CATALOG_PATH.is_file():
        log.warning("Файл каталога специализаций не найден: %s", CATALOG_PATH)
        return 0, ()

    try:
        with CATALOG_PATH.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError):
        log.exception("Не удалось прочитать каталог специализаций")
        return 0, ()

    if not isinstance(payload, dict) or not isinstance(payload.get("specs"), list):
        log.error("Каталог специализаций имеет неверный формат")
        return 0, ()

    version = payload.get("version", 1)
    try:
        version = int(version)
    except (TypeError, ValueError):
        version = 1

    specs: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    seen_names: set[tuple[str, str]] = set()

    for raw in payload["specs"]:
        if not isinstance(raw, dict):
            continue

        role = normalize_role(str(raw.get("role", "")))
        name = str(raw.get("name", "")).strip()
        icon_file = Path(str(raw.get("icon_file", "")).strip()).name
        spec_id = str(raw.get("id", "")).strip()

        if role is None or not name or not spec_id:
            log.warning("Пропущена запись каталога специализаций: %r", raw)
            continue
        if len(name) > MAX_SPEC_NAME_LENGTH:
            log.warning("Слишком длинное название в каталоге: %s", name)
            continue
        if not icon_file or Path(icon_file).suffix.casefold() not in {
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".gif",
        }:
            log.warning("Некорректная иконка в каталоге для %s: %r", spec_id, icon_file)
            continue
        if spec_id in seen_ids or (role, name.casefold()) in seen_names:
            log.warning("Дубликат в каталоге специализаций: %s", spec_id)
            continue

        seen_ids.add(spec_id)
        seen_names.add((role, name.casefold()))
        specs.append(
            {
                "id": spec_id,
                "role": role,
                "name": name,
                "icon_file": icon_file,
            }
        )

    return version, tuple(specs)


def bundled_catalog() -> tuple[int, list[dict[str, str]]]:
    version, specs = _load_catalog()
    return version, copy.deepcopy(list(specs))
