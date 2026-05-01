import asyncio
from typing import Dict, Any
from models.product import Product
from models.analysis import ProductAnalysis
from scraper.ebay import EbayScraper
from scraper.amazon import AmazonScraper
from scraper.google_shopping import GoogleShoppingScraper
from scraper.walmart import WalmartScraper
from scraper.facebook_mp import FacebookMPEstimator


class Layer2Market:
    def __init__(self) -> None:
        self._ebay = EbayScraper()
        self._amazon = AmazonScraper()
        self._google = GoogleShoppingScraper()
        self._walmart = WalmartScraper()
        self._fb = FacebookMPEstimator()

    async def analyze_all(self, products: list[Product]) -> list[ProductAnalysis]:
        async def _safe(p: Product) -> ProductAnalysis:
            try:
                return await asyncio.wait_for(self._analyze_product(p), timeout=100.0)
            except (asyncio.TimeoutError, Exception):
                return ProductAnalysis(
                    name=p.normalized_name or p.name,
                    condition=p.condition.value,
                    quantity=p.quantity,
                    listed_msrp=p.listed_msrp,
                )
        return list(await asyncio.gather(*[_safe(p) for p in products]))

    async def _analyze_product(self, product: Product) -> ProductAnalysis:
        name = product.normalized_name or product.name
        condition_str = product.condition.value

        ebay_task = self._ebay.get_sold_data(name, condition_str)
        amazon_task = self._amazon.get_prices(name)
        google_task = self._google.get_price(name)
        walmart_task = self._walmart.get_price(name)

        ebay_data, amazon_data, google_price, walmart_price = await asyncio.gather(
            ebay_task, amazon_task, google_task, walmart_task
        )

        fb_price = await self._fb.estimate_price(name, condition_str, ebay_data.get("avg"))

        return ProductAnalysis(
            name=name,
            condition=condition_str,
            quantity=product.quantity,
            listed_msrp=product.listed_msrp,
            real_msrp=product.real_msrp,
            fake_msrp=product.fake_msrp,
            ebay_sold_avg=ebay_data.get("avg"),
            ebay_sold_median=ebay_data.get("median"),
            ebay_sold_min=ebay_data.get("min"),
            ebay_sold_max=ebay_data.get("max"),
            amazon_new=amazon_data.get("new_price"),
            amazon_used=amazon_data.get("used_price"),
            google_shopping_price=google_price,
            walmart_price=walmart_price,
            fb_estimated_price=fb_price,
        )
