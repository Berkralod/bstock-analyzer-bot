from models.analysis import Decision, RiskLevel, PlatformResult


def make_decision(roi: float, sell_through: float | None = None) -> tuple[Decision, RiskLevel | None]:
    st = sell_through if sell_through is not None else 0.6

    if roi > 100 and st > 0.70:
        return Decision.BUY, RiskLevel.LOW
    if roi >= 70 and st > 0.60:
        return Decision.BUY, RiskLevel.MEDIUM
    if roi >= 50 and st > 0.50:
        return Decision.RISKY, RiskLevel.HIGH_RISKY
    if roi >= 30 and st >= 0.40:
        return Decision.RISKY, RiskLevel.MEDIUM_RISKY
    if roi >= 15 and st >= 0.30:
        return Decision.RISKY, RiskLevel.VERY_RISKY
    return Decision.SKIP, None


def compute_max_bid(
    total_estimated_revenue: float,
    buyers_premium_rate: float,
    shipping_cost: float,
) -> float:
    gross = total_estimated_revenue * 0.45
    # bid + bid*premium + shipping = gross  →  bid = (gross - shipping) / (1 + premium)
    bid = (gross - shipping_cost) / (1 + buyers_premium_rate)
    return max(0.0, round(bid, 2))


def choose_best_platform(platform_totals: dict[str, PlatformResult]) -> tuple[str | None, float]:
    best = None
    best_roi = -999.0
    for name, result in platform_totals.items():
        if result.roi > best_roi:
            best_roi = result.roi
            best = name
    return best, best_roi
