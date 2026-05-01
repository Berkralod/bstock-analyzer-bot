import httpx
from bs4 import BeautifulSoup
from typing import Optional
import config
from utils.cache import Cache
from utils.helpers import clean_price

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


def _bright_data_proxies() -> dict | None:
    key = getattr(config, "BRIGHTDATA_API_KEY", "")
    zone = getattr(config, "BRIGHTDATA_ZONE", "web_unlocker1")
    if not key:
        return None
    return {
        "http://": f"http://zone-{zone}:{key}@brd.superproxy.io:22225",
        "https://": f"http://zone-{zone}:{key}@brd.superproxy.io:22225",
    }


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
        html = await self._fetch(url)
        if not html:
            return None
        soup = BeautifulSoup(html, "lxml")
        prices = []
        for el in soup.select("[itemprop='price'], .price-main, [class*='price']")[:5]:
            raw = el.get("content") or el.get_text()
            p = clean_price(raw)
            if p and 1 < p < 10000:
                prices.append(p)
        return min(prices) if prices else None

    async def _fetch(self, url: str) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                r = await client.get(url, headers=HEADERS)
                if r.status_code == 200:
                    return r.text
        except Exception:
            pass
        proxies = _bright_data_proxies()
        if proxies:
            try:
                async with httpx.AsyncClient(proxies=proxies, timeout=20.0, verify=False) as client:
                    r = await client.get(url, headers=HEADERS)
                    return r.text
            except Exception:
                pass
        return None
