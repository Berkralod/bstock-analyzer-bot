import asyncio
from typing import List
from models.product import Product
from scraper.google_shopping import GoogleShoppingScraper


class Layer1Screener:
    """Quick screening: detects fake MSRP by comparing listed vs real retail price."""

    def __init__(self) -> None:
        self._google = GoogleShoppingScraper()

    async def screen_all(self, products: List[Product]) -> None:
        await asyncio.gather(*[self._screen_product(p) for p in products])

    async def _screen_product(self, product: Product) -> None:
        name = product.normalized_name or product.name
        real_price = await self._google.get_price(name)
        if real_price:
            product.real_msrp = real_price
            if product.listed_msrp and real_price < product.listed_msrp * 0.80:
                product.fake_msrp = True
        else:
            product.real_msrp = product.listed_msrp
