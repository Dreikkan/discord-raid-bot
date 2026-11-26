from __future__ import annotations

ROLE_ORDER: tuple[str, ...] = ("tank", "heal", "dd")

ROLE_LABELS: dict[str, str] = {
    "tank": "Танк",
    "heal": "Хил",
    "dd": "ДД",
}

ROLE_ALIASES: dict[str, str] = {
    "tank": "tank",
    "танк": "tank",
    "heal": "heal",
    "хил": "heal",
    "healer": "heal",
    "dd": "dd",
    "дд": "dd",
    "dps": "dd",
    "урон": "dd",
}

STATUS_MAIN = "main"
STATUS_BENCH = "bench"
STATUS_ABSENT = "absent"

STATUS_LABELS: dict[str, str] = {
    STATUS_MAIN: "Основной состав",
    STATUS_BENCH: "Скамья запасных",
    STATUS_ABSENT: "Буду отсутствовать",
}

DEFAULT_TITLE = "Еженедельный рейд"
DEFAULT_LIMITS: dict[str, int] = {"tank": 1, "heal": 2, "dd": 7}
DEFAULT_ROLE_EMOJIS: dict[str, str] = {
    "tank": "<:tank:1575602137033875720>",
    "heal": "<:heal:1575602120672022588>",
    "dd": "<:DD:1575602114674032793>",
}
DEFAULT_TIMEZONE = "Europe/Moscow"

EMBED_COLOR = 0x992D22
BENCH_EMOJI = "🪑"
ABSENT_EMOJI = "❌"
REMINDER_MINUTES = 15
REMINDER_LOOP_SECONDS = 20
REMINDER_RETRY_SECONDS = 5 * 60

WIZARD_TIMEOUT_SECONDS = 15 * 60
MAX_SPECS_PER_ROLE = 25

PUBLIC_BUTTON_PREFIX = "raid:register:"
MAX_DESCRIPTION_LENGTH = 3000
MAX_TITLE_LENGTH = 256
MAX_SPEC_NAME_LENGTH = 100

# The total character budget for an embed is 6000. Leave a small reserve
# for the parts that Discord counts slightly differently.
EMBED_TOTAL_SOFT_LIMIT = 5800
