from __future__ import annotations

import copy
import json
import logging
from functools import lru_cache
from pathlib import Path

from .constants import MAX_SPEC_NAME_LENGTH
from .specs import SpecInputError, normalize_emoji, normalize_role

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = PROJECT_ROOT / "config" / "specializations.json"


@lru_cache(maxsize=1)
def _load_catalog() -> tuple[int, tuple[dict[str, str], ...]]:
    if not CATALOG_PATH.is_file():
        log.error("Файл каталога специализаций не найден: %s", CATALOG_PATH)
        return 0, ()

    try:
        with CATALOG_PATH.open("r", encoding="utf-8-sig") as file:
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
        spec_id = str(raw.get("id", "")).strip()

        if role is None or not name or not spec_id:
            log.warning("Пропущена запись каталога специализаций: %r", raw)
            continue
        if len(name) > MAX_SPEC_NAME_LENGTH:
            log.warning("Слишком длинное название в каталоге: %s", name)
            continue
        if spec_id in seen_ids or (role, name.casefold()) in seen_names:
            log.warning("Дубликат в каталоге специализаций: %s", spec_id)
            continue

        try:
            emoji = normalize_emoji(str(raw.get("emoji", "")), required=True)
        except SpecInputError:
            log.exception("Некорректная иконка в каталоге для %s", spec_id)
            continue

        seen_ids.add(spec_id)
        seen_names.add((role, name.casefold()))
        specs.append(
            {
                "id": spec_id,
                "role": role,
                "name": name,
                "emoji": emoji,
            }
        )

    return version, tuple(specs)


def bundled_catalog() -> list[dict[str, str]]:
    _, specs = _load_catalog()
    return copy.deepcopy(list(specs))
