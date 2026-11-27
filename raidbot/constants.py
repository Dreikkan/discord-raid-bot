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
RAID_ROLE_MENTION_ID = 1482725169884565627
REMINDER_MINUTES = 15
REMINDER_LOOP_SECONDS = 20
REMINDER_RETRY_SECONDS = 5 * 60
MAX_REMINDER_DELETE_MINUTES = 10080
MAX_REMINDER_DESCRIPTION_LENGTH = 1500

# ------------------------------------------------------------------ Economy
CURRENCY_NAME = "Осколки гармонии"
CURRENCY_EMOJI = "✨"

GACHA_SINGLE_COST = 100
GACHA_TEN_COST = 900
GACHA_PITY = 80

RAID_REWARD_MAIN = 50
RAID_REWARD_BENCH = 15
ACTIVITY_REWARD = 25

ACTIVITY_CHECKIN_CUSTOM_ID = "activity:checkin"

MAX_GACHA_ITEM_NAME_LENGTH = 100
MAX_GACHA_ITEM_DESCRIPTION_LENGTH = 500
MAX_GACHA_ITEM_WEIGHT = 10000
MAX_GACHA_IMAGE_URL_LENGTH = 500
MAX_GACHA_IMAGE_BYTES = 8 * 1024 * 1024

WEEKDAY_LABELS: tuple[str, ...] = (
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
)

WIZARD_TIMEOUT_SECONDS = 15 * 60
MAX_SPECS_PER_ROLE = 25

PUBLIC_BUTTON_PREFIX = "raid:register:"
MAX_TITLE_LENGTH = 256
MAX_SPEC_NAME_LENGTH = 100

# The total character budget for an embed is 6000. Leave a small reserve
# for the parts that Discord counts slightly differently.
EMBED_TOTAL_SOFT_LIMIT = 5800
