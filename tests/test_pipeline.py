import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from models.lot import Lot
from models.product import Product, Condition
from models.analysis import Decision
from analyzer.pipeline import AnalysisPipeline
from analyzer.condition import get_multiplier
from analyzer.cost_calculator import calc_ebay, calc_shopify, calc_facebook
from analyzer.decision_engine import make_decision, compute_max_bid


# --- Condition multiplier tests ---

def test_condition_multipliers():
    assert get_multiplier(Condition.NEW) == 1.00
    assert get_multiplier(Condition.SALVAGE) == 0.15
    assert get_multiplier(Condition.UNTESTED) == 0.35


# --- Cost calculator tests ---

def test_calc_ebay_basic():
    result = calc_ebay(sale_price=100.0, cost_per_unit=50.0)
    assert result["fee"] == pytest.approx(13.0)
    assert result["net"] < 100.0


def test_calc_facebook_no_fee():
    result = calc_facebook(sale_price=80.0, cost_per_unit=40.0)
    assert result["fee"] == 0.0
    assert result["net"] == pytest.approx(40.0)


# --- Decision engine tests ---

def test_decision_buy_low_risk():
    dec, risk = make_decision(roi=120, sell_through=0.80)
    assert dec == Decision.BUY
    assert "düşük" in risk.value


def test_decision_skip():
    dec, risk = make_decision(roi=5, sell_through=0.20)
    assert dec == Decision.SKIP


def test_decision_risky():
    dec, risk = make_decision(roi=55, sell_through=0.55)
    assert dec == Decision.RISKY


def test_max_bid():
    bid = compute_max_bid(
        total_estimated_revenue=5000.0,
        buyers_premium_rate=0.15,
        shipping_cost=380.0,
    )
    assert bid > 0
    assert bid < 5000.0


# --- Integration-style pipeline smoke test ---

@pytest.mark.asyncio
async def test_pipeline_smoke():
    lot = Lot(
        url="https://bstock.com/lot/12345",
        lot_id="12345",
        current_bid=500.0,
        shipping_cost=100.0,
        buyers_premium_rate=0.15,
        products=[
            Product(name="DeWalt DCD791 Drill", condition=Condition.LIKE_NEW, quantity=2, listed_msrp=199.0),
            Product(name="Ninja BL610 Blender", condition=Condition.REFURBISHED, quantity=1, listed_msrp=89.0),
        ],
    )
    lot.compute_totals()

    pipeline = AnalysisPipeline()

    with (
        patch.object(pipeline._haiku, "normalize_product_names", new_callable=AsyncMock) as mock_norm,
        patch.object(pipeline._layer1._google, "get_price", new_callable=AsyncMock) as mock_google,
        patch.object(pipeline._layer2._ebay, "get_sold_data", new_callable=AsyncMock) as mock_ebay,
        patch.object(pipeline._layer2._amazon, "get_prices", new_callable=AsyncMock) as mock_amazon,
        patch.object(pipeline._layer2._google, "get_price", new_callable=AsyncMock) as mock_gshop,
        patch.object(pipeline._layer2._walmart, "get_price", new_callable=AsyncMock) as mock_walmart,
        patch.object(pipeline._layer2._fb, "estimate_price", new_callable=AsyncMock) as mock_fb,
        patch.object(pipeline._layer3._ebay, "get_active_count", new_callable=AsyncMock) as mock_active,
    ):
        mock_norm.return_value = [
            {"original": "DeWalt DCD791 Drill", "normalized": "DeWalt DCD791", "brand": "DeWalt", "model": "DCD791", "category": "Power Tools"},
            {"original": "Ninja BL610 Blender", "normalized": "Ninja BL610", "brand": "Ninja", "model": "BL610", "category": "Kitchen"},
        ]
        mock_google.return_value = 169.0
        mock_ebay.return_value = {"avg": 89.0, "median": 88.0, "min": 70.0, "max": 110.0, "count": 25}
        mock_amazon.return_value = {"new_price": 169.0, "used_price": 95.0}
        mock_gshop.return_value = 169.0
        mock_walmart.return_value = 159.0
        mock_fb.return_value = 105.0
        mock_active.return_value = 8

        result = await pipeline.run(lot)

    assert result.product_count == 3
    assert result.total_cost is not None
    assert result.max_bid > 0
    assert len(result.products) == 2
    assert result.platform_totals
