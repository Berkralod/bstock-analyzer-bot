import asyncio
import time
from typing import List

import config
from models.lot import Lot
from models.product import Product
from models.analysis import AnalysisResult, PlatformResult, ProductAnalysis
from utils.haiku import HaikuClient
from utils.helpers import chunk_list
from analyzer.layer1_screen import Layer1Screener
from analyzer.layer2_market import Layer2Market
from analyzer.layer3_deep import Layer3Deep
from analyzer.condition import get_multiplier
from analyzer.cost_calculator import calc_ebay, calc_shopify, calc_amazon, calc_facebook
from analyzer.decision_engine import make_decision, compute_max_bid, choose_best_platform


class AnalysisPipeline:
    def __init__(self) -> None:
        self._haiku = HaikuClient()
        self._layer1 = Layer1Screener()
        self._layer2 = Layer2Market()
        self._layer3 = Layer3Deep()

    async def run(self, lot: Lot) -> AnalysisResult:
        start = time.monotonic()

        result = AnalysisResult(
            lot_url=lot.url,
            lot_id=lot.lot_id,
            current_bid=lot.current_bid,
            shipping_cost=lot.shipping_cost,
            buyers_premium=lot.buyers_premium_amount,
            total_cost=lot.total_cost,
            product_count=lot.product_count,
        )

        if not lot.products:
            result.error = "No products found in lot."
            return result

        # Normalize product names in batches via Haiku
        await self._normalize_names(lot.products)

        # Layer 1: skipped (Google Shopping too slow in production)

        # Layer 2: Market price analysis (all products, parallel)
        product_analyses: List[ProductAnalysis] = await self._layer2.analyze_all(lot.products)

        # Compute per-unit cost share
        total_units = max(1, sum(p.quantity for p in lot.products))
        cost_per_unit = (lot.total_cost or 0) / total_units

        for pa in product_analyses:
            pa.cost_per_unit = cost_per_unit

        # Layer 3: skipped (eBay active count lookup too slow in production)

        # Platform calculations for each product
        for pa in product_analyses:
            pa.platform_results = self._compute_platform_results(pa, lot)

        result.products = product_analyses

        # Aggregate platform totals
        result.platform_totals = self._aggregate_platforms(product_analyses, lot)

        # Best platform & decision
        best_name, best_roi = choose_best_platform(result.platform_totals)
        result.best_platform = best_name
        result.best_roi = best_roi

        best_result = result.platform_totals.get(best_name) if best_name else None
        if best_result:
            decision, risk = make_decision(best_roi, None)
            result.overall_decision = decision

        # Max bid
        total_revenue = sum(
            pr.estimated_revenue
            for pa in product_analyses
            for pr in pa.platform_results
            if pr.platform == (best_name or "eBay")
        )
        result.max_bid = compute_max_bid(
            total_revenue,
            lot.buyers_premium_rate,
            lot.shipping_cost or 0,
        )

        # Capital return estimate
        days_list = [
            pa.estimated_days_to_sell
            for pa in product_analyses
            if pa.estimated_days_to_sell
        ]
        if days_list:
            result.estimated_capital_return_days = int(sum(days_list) / len(days_list))

        result.analysis_duration_seconds = round(time.monotonic() - start, 1)
        return result

    async def _normalize_names(self, products: List[Product]) -> None:
        all_names = [p.name for p in products]
        for batch in chunk_list(all_names, 20):
            try:
                normalized = await self._haiku.normalize_product_names(batch)
                for item in normalized:
                    original = item.get("original", "")
                    for p in products:
                        if p.name == original:
                            p.normalized_name = item.get("normalized", original)
                            p.brand = item.get("brand")
                            p.category = item.get("category")
                            if not p.model_number:
                                p.model_number = item.get("model")
                            break
            except Exception:
                pass

    def _quick_roi(self, pa: ProductAnalysis, cost_per_unit: float) -> float:
        ebay_avg = pa.ebay_sold_avg or 0
        if not ebay_avg or not cost_per_unit:
            return 0
        net = ebay_avg * 0.87 - cost_per_unit
        return (net / cost_per_unit * 100) if cost_per_unit > 0 else 0

    def _compute_platform_results(self, pa: ProductAnalysis, lot: Lot) -> list:
        from models.product import Condition
        multiplier = get_multiplier(Condition(pa.condition) if pa.condition else Condition.UNKNOWN)
        cost = pa.cost_per_unit
        results = []

        def build(platform: str, base_price: float | None, calc_fn, **kwargs) -> PlatformResult | None:
            if base_price is None:
                return None
            price = base_price * multiplier
            data = calc_fn(price, cost, **kwargs)
            decision, risk = make_decision(data["roi"], pa.sell_through_rate)
            return PlatformResult(
                platform=platform,
                estimated_revenue=round(price * pa.quantity, 2),
                fees=round(data["fee"] * pa.quantity, 2),
                shipping_out=round(data["shipping_out"] * pa.quantity, 2),
                packaging=round(data["packaging"] * pa.quantity, 2),
                net_profit=round(data["net"] * pa.quantity, 2),
                roi=round(data["roi"], 1),
                decision=decision,
                risk_level=risk,
            )

        for platform, price, fn, kwargs in [
            ("eBay", pa.ebay_sold_avg, calc_ebay, {}),
            ("Shopify", pa.amazon_new, calc_shopify, {}),
            ("Amazon", pa.amazon_used, calc_amazon, {}),
            ("Facebook/Flea", pa.fb_estimated_price, calc_facebook, {}),
        ]:
            r = build(platform, price, fn, **kwargs)
            if r:
                results.append(r)

        return results

    def _aggregate_platforms(self, analyses: list, lot: Lot) -> dict:
        totals: dict[str, dict] = {}

        for pa in analyses:
            for pr in pa.platform_results:
                if pr.platform not in totals:
                    totals[pr.platform] = {
                        "revenue": 0, "fees": 0, "shipping": 0,
                        "packaging": 0, "net": 0, "cost": 0,
                    }
                t = totals[pr.platform]
                t["revenue"] += pr.estimated_revenue
                t["fees"] += pr.fees
                t["shipping"] += pr.shipping_out
                t["packaging"] += pr.packaging
                t["net"] += pr.net_profit
                t["cost"] += pa.cost_per_unit * pa.quantity

        result = {}
        for platform, t in totals.items():
            roi = (t["net"] / t["cost"] * 100) if t["cost"] > 0 else 0
            decision, risk = make_decision(roi)
            result[platform] = PlatformResult(
                platform=platform,
                estimated_revenue=round(t["revenue"], 2),
                fees=round(t["fees"], 2),
                shipping_out=round(t["shipping"], 2),
                packaging=round(t["packaging"], 2),
                net_profit=round(t["net"], 2),
                roi=round(roi, 1),
                decision=decision,
                risk_level=risk,
            )

        return result
