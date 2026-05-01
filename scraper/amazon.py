import httpx
from bs4 import BeautifulSoup
from typing import Dict, Any
import config
from utils.cache import Cache
from utils.helpers import clean_price

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
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


class AmazonScraper:
    async def get_prices(self, product_name: str) -> Dict[str, Any]:
        cached = await Cache.get("amazon", product_name)
        if cached:
            return cached
        result = await self._scrape(product_name)
        await Cache.set("amazon", product_name, result, config.CACHE_TTL_AMAZON)
        return result

    async def _scrape(self, product_name: str) -> Dict[str, Any]:
        url = f"https://www.amazon.com/s?k={product_name.replace(' ', '+')}"
        html = await self._fetch(url)
        if not html:
            return {"new_price": None, "used_price": None}
        return self._extract_prices(html)

    async def _fetch(self, url: str) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                r = await client.get(url, headers=HEADERS)
                if r.status_code == 200 and len(r.text) > 500:
                    return r.text
        except Exception:
            pass
        proxies = _bright_data_proxies()
        if proxies:
            try:
                async with httpx.AsyncClient(proxies=proxies, timeout=25.0, verify=False) as client:
                    r = await client.get(url, headers=HEADERS)
                    return r.text
            except Exception:
                pass
        return None

    def _extract_prices(self, html: str) -> Dict[str, Any]:
        soup = BeautifulSoup(html, "lxml")
        prices = []
        for el in soup.select(".a-price .a-offscreen")[:5]:
            p = clean_price(el.get_text())
            if p and p > 0:
                prices.append(p)
        new_price = min(prices) if prices else None
        used_price = round(new_price * 0.65, 2) if new_price else None
        return {"new_price": new_price, "used_price": used_price}
