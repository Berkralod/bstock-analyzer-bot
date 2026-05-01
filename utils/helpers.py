import re
from typing import List, TypeVar, Iterator
from models.product import Condition

T = TypeVar("T")


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
