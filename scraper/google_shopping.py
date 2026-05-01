import httpx
from bs4 import BeautifulSoup
from typing import Optional
import config
from utils.cache import Cache
from utils.helpers import clean_price


class GoogleShoppingScraper:
    def __init__(self) -> None:
        self._proxy = {
            "http://": config.BRIGHTDATA_PROXY_URL,
            "https://": config.BRIGHTDATA_PROXY_URL,
        }

    async def get_price(self, product_name: str) -> Optional[float]:
        cached = await Cache.get("google_shopping", product_name)
        if cached is not None:
            return cached

        price = await self._scrape(product_name)
        await Cache.set("google_shopping", product_name, price, config.CACHE_TTL_GOOGLE)
        return price

    async def _scrape(self, product_name: str) -> Optional[float]:
        url = f"https://www.google.com/search?q={product_name.replace(' ', '+')}&tbm=shop"
        try:
            async with httpx.AsyncClient(proxies=self._proxy, timeout=20.0, verify=False) as client:
                resp = await client.get(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                        "Accept": "text/html",
                    },
                )
                html = resp.text

            soup = BeautifulSoup(html, "lxml")
            prices = []
            for el in soup.select(".a8Pemb, .kHxwFf, [class*='price']")[:5]:
                p = clean_price(el.get_text())
                if p and 1 < p < 10000:
                    prices.append(p)

            return min(prices) if prices else None
        except Exception:
            return None
