import httpx
from bs4 import BeautifulSoup
from typing import Optional
import config
from utils.cache import Cache
from utils.helpers import clean_price


class WalmartScraper:
    def __init__(self) -> None:
        self._proxy = {
            "http://": config.BRIGHTDATA_PROXY_URL,
            "https://": config.BRIGHTDATA_PROXY_URL,
        }

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
            async with httpx.AsyncClient(proxies=self._proxy, timeout=20.0, verify=False) as client:
                resp = await client.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
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
