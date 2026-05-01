import httpx
import json
import re
from typing import Dict, Any, Optional
import config
from utils.cache import Cache
from utils.helpers import clean_price


BRIGHTDATA_API_URL = "https://api.brightdata.com/datasets/v3/trigger"


class AmazonScraper:
    def __init__(self) -> None:
        self._proxy = {
            "http://": config.BRIGHTDATA_PROXY_URL,
            "https://": config.BRIGHTDATA_PROXY_URL,
        }

    async def get_prices(self, product_name: str) -> Dict[str, Any]:
        cached = await Cache.get("amazon", product_name)
        if cached:
            return cached

        result = await self._scrape_via_proxy(product_name)
        await Cache.set("amazon", product_name, result, config.CACHE_TTL_AMAZON)
        return result

    async def _scrape_via_proxy(self, product_name: str) -> Dict[str, Any]:
        search_url = f"https://www.amazon.com/s?k={product_name.replace(' ', '+')}"
        try:
            async with httpx.AsyncClient(proxies=self._proxy, timeout=25.0, verify=False) as client:
                resp = await client.get(
                    search_url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                )
                html = resp.text

            prices = self._extract_prices(html)
            return prices
        except Exception:
            return {"new_price": None, "used_price": None}

    def _extract_prices(self, html: str) -> Dict[str, Any]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")

        prices = []
        price_els = soup.select(".a-price .a-offscreen")
        for el in price_els[:5]:
            p = clean_price(el.get_text())
            if p and p > 0:
                prices.append(p)

        new_price = min(prices) if prices else None

        used_el = soup.select_one(".olp-used, [data-action='show-all-offers-display']")
        used_price = None
        if used_el:
            used_price_raw = used_el.get_text()
            used_price = clean_price(used_price_raw)
            if used_price and used_price > (new_price or 999999):
                used_price = None

        if new_price and not used_price:
            used_price = round(new_price * 0.65, 2)

        return {"new_price": new_price, "used_price": used_price}
