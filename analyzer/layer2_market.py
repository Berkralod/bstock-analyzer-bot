import asyncio
from models.product import Product, Condition
from models.analysis import ProductAnalysis
from scraper.ebay import EbayScraper
from analyzer.condition import get_multiplier


class Layer2Market:
    def __init__(self) -> None:
        self._ebay = EbayScraper()

    async def analyze_all(self, products: list[Product]) -> list[ProductAnalysis]:
        tasks = [self._analyze_product(p) for p in products]
        return list(await asyncio.gather(*tasks, return_exceptions=False))

    async def _analyze_product(self, product: Product) -> ProductAnalysis:
        name = product.normalized_name or product.name
        condition_str = product.condition.value

        # Try live eBay data with aggressive timeout
        ebay_data: dict = {}
        try:
            ebay_data = await asyncio.wait_for(
                self._ebay.get_sold_data(name, condition_str), timeout=8.0
            )
        except Exception:
            pass

        ebay_avg = ebay_data.get("avg")

        # Fallback: estimate from MSRP × condition multiplier if eBay fails
        if ebay_avg is None and product.listed_msrp:
            mult = get_multiplier(product.condition)
            # eBay sold prices are typically ~90% of condition-adjusted MSRP
            ebay_avg = round(product.listed_msrp * mult * 0.90, 2)

        amazon_new = round(ebay_avg * 1.15, 2) if ebay_avg else None
        amazon_used = round(ebay_avg * 0.80, 2) if ebay_avg else None
        fb_price = round(ebay_avg * 1.18, 2) if ebay_avg else None

        return ProductAnalysis(
            name=name,
            condition=condition_str,
            quantity=product.quantity,
            listed_msrp=product.listed_msrp,
            real_msrp=product.real_msrp,
            fake_msrp=product.fake_msrp,
            ebay_sold_avg=ebay_avg,
            ebay_sold_median=ebay_data.get("median"),
            ebay_sold_min=ebay_data.get("min"),
            ebay_sold_max=ebay_data.get("max"),
            amazon_new=amazon_new,
            amazon_used=amazon_used,
            google_shopping_price=None,
            walmart_price=None,
            fb_estimated_price=fb_price,
        )
