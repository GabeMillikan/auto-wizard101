API_ROOT = "https://www.wizard101central.com"
CATEGORIES = (
    "hats",
    "robes",
    "boots",
    "athames",
    "amulets",
    "rings",
    "decks",
    "mounts",
    "jewels",
    "talents",
)
CATEGORIES_SINGULAR = (
    "hat",
    "robe",
    "boot",
    "athame",
    "amulet",
    "ring",
    "deck",
    "mount",
    "jewel",
    "talents",
)
CATEGORIES_IGNORE_PLURALITY = CATEGORIES + CATEGORIES_SINGULAR
CATEGORY_LOOKUP: dict[str, str] = dict(zip(CATEGORIES_IGNORE_PLURALITY, CATEGORIES * 2))
SCHOOLS = "fire", "storm", "ice", "myth", "death", "life", "balance", "sun", "star", "moon"
