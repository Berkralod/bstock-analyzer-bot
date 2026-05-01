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


def calc_shopify(
    sale_price: float,
    cost_per_unit: float,
    weight_lbs: float | None = None,
    category: str | None = None,
) -> dict:
    fee = sale_price * config.SHOPIFY_FEE_RATE + config.SHOPIFY_FEE_FIXED
    ship = estimate_shipping_cost(weight_lbs, category)
    net = sale_price - fee - ship - cost_per_unit
    roi = (net / cost_per_unit * 100) if cost_per_unit > 0 else 0
    return {"fee": fee, "shipping_out": ship, "packaging": 0.0, "net": net, "roi": roi}


def calc_amazon(
    sale_price: float,
    cost_per_unit: float,
    weight_lbs: float | None = None,
) -> dict:
    referral = sale_price * config.AMAZON_REFERRAL_RATE
    fba = config.AMAZON_FBA_FEE
    net = sale_price - referral - fba - cost_per_unit
    roi = (net / cost_per_unit * 100) if cost_per_unit > 0 else 0
    return {"fee": referral + fba, "shipping_out": 0.0, "packaging": 0.0, "net": net, "roi": roi}


def calc_facebook(
    sale_price: float,
    cost_per_unit: float,
    table_share: float = 0.0,
) -> dict:
    net = sale_price - table_share - cost_per_unit
    roi = (net / cost_per_unit * 100) if cost_per_unit > 0 else 0
    return {"fee": 0.0, "shipping_out": 0.0, "packaging": 0.0, "net": net, "roi": roi}
