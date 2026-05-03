import re
from typing import List, TypeVar, Iterator
from models.product import Condition

T = TypeVar("T")

_VENDOR_SHORT: dict[str, str] = {
    "APPLE COMPUTER INC": "Apple",
    "APPLE INC": "Apple",
    "SAMSUNG ELECTRONICS AMERICA": "Samsung",
    "SAMSUNG ELECTRONICS": "Samsung",
    "MICROSOFT CORPORATION": "Microsoft",
    "SONY CORPORATION": "Sony",
    "SONY ELECTRONICS": "Sony",
    "DELL TECHNOLOGIES INC": "Dell",
    "DELL INC": "Dell",
    "HP INC": "HP",
    "HEWLETT PACKARD": "HP",
    "LENOVO GROUP LIMITED": "Lenovo",
    "LENOVO": "Lenovo",
    "LG ELECTRONICS INC": "LG",
    "LG ELECTRONICS": "LG",
}

# B-Stock internal abbreviations → human-readable
_PHRASE_MAP: dict[str, str] = {
    "MGC KB FOR": "Magic Keyboard for",
    "MGC KB": "Magic Keyboard",
    "MGC MOUSE": "Magic Mouse",
    "MGC TRACKPAD": "Magic Trackpad",
    "APPL PENCIL": "Apple Pencil",
    "APCL PENCIL": "Apple Pencil",
}

# Trailing noise tokens (color/finish codes that don't help eBay search)
_NOISE_TOKENS = {
    "BL", "WHT", "BLK", "SLV", "GLD", "RED", "GRY", "GRPH",
    "MIDNIGHT", "STARLIGHT", "PINK", "PURPLE", "YELLOW",
}


def clean_ebay_query(name: str) -> str:
    """Convert raw B-Stock product name to a clean eBay search query."""
    if not name:
        return name

    # Replace verbose vendor prefix with short brand name
    upper = name.upper()
    for vendor, short in _VENDOR_SHORT.items():
        if upper.startswith(vendor):
            name = short + " " + name[len(vendor):].strip()
            break

    # Expand B-Stock abbreviations (case-insensitive, whole-word)
    for abbrev, expansion in _PHRASE_MAP.items():
        name = re.sub(r"(?<!\w)" + re.escape(abbrev) + r"(?!\w)", expansion, name, flags=re.IGNORECASE)

    # Drop trailing noise tokens (color/finish codes)
    words = name.split()
    while words and words[-1].upper() in _NOISE_TOKENS:
        words.pop()

    return re.sub(r"\s+", " ", " ".join(words)).strip()


def clean_price(text: str) -> float | None:
    if not text:
        return None
    cleaned = re.sub(r"[^\d.]", "", str(text).replace(",", ""))
    try:
        return float(cleaned)
    except ValueError:
        return None


def normalize_condition(raw: str) -> Condition:
    r = raw.lower().strip()
    if any(x in r for x in ["new", "sealed", "nib", "nwt"]):
        if "open" in r or "ob" in r:
            return Condition.OPEN_BOX
        return Condition.NEW
    if any(x in r for x in ["like new", "excellent"]):
        return Condition.LIKE_NEW
    if "open box" in r or "open-box" in r:
        return Condition.OPEN_BOX
    if any(x in r for x in ["refurb", "renewed", "certified"]):
        return Condition.REFURBISHED
    if "used" in r and any(x in r for x in ["good", "very good"]):
        return Condition.USED_GOOD
    if "used" in r and any(x in r for x in ["accept", "fair"]):
        return Condition.USED_ACCEPTABLE
    if any(x in r for x in ["salvage", "damaged", "broken"]):
        return Condition.SALVAGE
    if any(x in r for x in ["parts", "repair", "as-is"]):
        return Condition.FOR_PARTS
    if any(x in r for x in ["untested", "return", "customer return"]):
        return Condition.UNTESTED
    return Condition.UNKNOWN


def chunk_list(lst: List[T], size: int) -> Iterator[List[T]]:
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


def estimate_shipping_cost(weight_lbs: float | None, category: str | None = None) -> float:
    if weight_lbs is None:
        return 8.0
    if weight_lbs <= 1:
        return 5.0
    if weight_lbs <= 5:
        return 8.0
    if weight_lbs <= 20:
        return 15.0
    if weight_lbs <= 50:
        return 35.0
    return 75.0


def extract_lot_id(url: str) -> str | None:
    # UUID pattern: /listings/details/{uuid} or /auctions/{uuid}
    m = re.search(r"/(?:listings/details|auctions|lots?)/([a-f0-9-]{8,})", url, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"/lot/(\d+)", url)
    if m:
        return m.group(1)
    m = re.search(r"lot[_-]?id[=:](\w+)", url, re.IGNORECASE)
    if m:
        return m.group(1)
    # Last segment of path
    m = re.search(r"/([a-f0-9-]{32,})", url)
    if m:
        return m.group(1)
    return None
