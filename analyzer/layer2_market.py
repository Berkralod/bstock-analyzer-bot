import asyncio
from models.product import Product
from models.analysis import ProductAnalysis
from scraper.ebay import EbayScraper
from utils.helpers import clean_ebay_query


class Layer2Market:
    def __init__(self) -> None:
        self._ebay = EbayScraper()

    async def analyze_all(self, products: list[Product]) -> list[ProductAnalysis]:
        tasks = [self._analyze_product(p) for p in products]
        return list(await asyncio.gather(*tasks, return_exceptions=False))

    async def _analyze_product(self, product: Product) -> ProductAnalysis:
        name = clean_ebay_query(product.normalized_name or product.name)
        condition_str = product.condition.value

        # eBay Finding API — real sold prices, no scraping
        ebay_data = await self._ebay.get_sold_data(name, condition_str)
        ebay_avg = ebay_data.get("avg")

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
        )
