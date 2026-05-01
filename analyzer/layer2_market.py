import asyncio
from models.product import Product
from models.analysis import ProductAnalysis
from scraper.ebay import EbayScraper


class Layer2Market:
    def __init__(self) -> None:
        self._ebay = EbayScraper()

    async def analyze_all(self, products: list[Product]) -> list[ProductAnalysis]:
        # Run all eBay lookups in parallel; each has its own internal semaphore
        tasks = [self._analyze_product(p) for p in products]
        return list(await asyncio.gather(*tasks, return_exceptions=False))

    async def _analyze_product(self, product: Product) -> ProductAnalysis:
        name = product.normalized_name or product.name
        condition_str = product.condition.value

        try:
            ebay_data = await asyncio.wait_for(
                self._ebay.get_sold_data(name, condition_str), timeout=25.0
            )
        except Exception:
            ebay_data = {}

        ebay_avg = ebay_data.get("avg")

        # Estimate Amazon/FB from eBay via multiplier (avoids slow external scrapers)
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
