import httpx
from bs4 import BeautifulSoup
from typing import Optional
import config
from utils.cache import Cache
from utils.helpers import clean_price


BRIGHTDATA_API_URL = "https://api.brightdata.com/request"


class WalmartScraper:
    async def get_price(self, product_name: str) -> Optional[float]:
        cached = await Cache.get("walmart", product_name)
        if cached is not None:
            return cached

        price = await self._scrape(product_name)
        await Cache.set("walmart", product_name, price, config.CACHE_TTL_GOOGLE)
        return price

    async def _scrape(self, product_name: str) -> Optional[float]:
        url = f"https://www.walmart.com/search?q={product_name.replace(' ', '+')}"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    BRIGHTDATA_API_URL,
                    headers={
                        "Authorization": f"Bearer {config.BRIGHTDATA_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={"zone": config.BRIGHTDATA_ZONE, "url": url, "format": "raw"},
                )
                html = resp.text

            soup = BeautifulSoup(html, "lxml")
            prices = []
            for el in soup.select("[itemprop='price'], .price-main, [class*='price']")[:5]:
                raw = el.get("content") or el.get_text()
                p = clean_price(raw)
                if p and 1 < p < 10000:
                    prices.append(p)

            return min(prices) if prices else None
        except Exception:
            return None
