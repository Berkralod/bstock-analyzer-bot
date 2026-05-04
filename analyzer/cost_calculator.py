import config
from utils.helpers import estimate_shipping_cost


def calc_ebay(
    sale_price: float,
    cost_per_unit: float,
    weight_lbs: float | None = None,
    category: str | None = None,
) -> dict:
    fee = sale_price * config.EBAY_FEE_RATE
    ship = estimate_shipping_cost(weight_lbs, category)
    pkg = config.PACKAGING_COST_PER_ITEM
    net = sale_price - fee - ship - pkg - cost_per_unit
    roi = (net / cost_per_unit * 100) if cost_per_unit > 0 else 0
    return {"fee": fee, "shipping_out": ship, "packaging": pkg, "net": net, "roi": roi}
