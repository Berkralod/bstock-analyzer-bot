from models.product import Condition

CONDITION_MULTIPLIERS: dict[Condition, float] = {
    Condition.NEW: 1.00,
    Condition.LIKE_NEW: 0.85,
    Condition.OPEN_BOX: 0.85,
    Condition.REFURBISHED: 0.70,
    Condition.USED_GOOD: 0.55,
    Condition.USED_ACCEPTABLE: 0.40,
    Condition.SALVAGE: 0.15,
    Condition.FOR_PARTS: 0.15,
    Condition.UNTESTED: 0.35,
    Condition.UNKNOWN: 0.50,
}


def get_multiplier(condition: Condition) -> float:
    return CONDITION_MULTIPLIERS.get(condition, 0.50)
