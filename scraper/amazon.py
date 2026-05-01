import httpx
import json
from typing import Dict, Any, Optional
import config
from utils.cache import Cache
from utils.helpers import clean_price


BRIGHTDATA_API_URL = "https://api.brightdata.com/request"


class AmazonScraper:
    async def get_prices(self, product_name: str) -> Dict[str, Any]:
        cached = await Cache.get("amazon", product_name)
        if cached:
            return cached

        result = await self._scrape(product_name)
        await Cache.set("amazon", product_name, result, config.CACHE_TTL_AMAZON)
        return result

    async def _scrape(self, product_name: str) -> Dict[str, Any]:
        search_url = f"https://www.amazon.com/s?k={product_name.replace(' ', '+')}"
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post(
                    BRIGHTDATA_API_URL,
                    headers={
                        "Authorization": f"Bearer {config.BRIGHTDATA_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={"zone": config.BRIGHTDATA_ZONE, "url": search_url, "format": "raw"},
                )
                html = resp.text

            return self._extract_prices(html)
        except Exception:
            return {"new_price": None, "used_price": None}

    def _extract_prices(self, html: str) -> Dict[str, Any]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")

        prices = []
        for el in soup.select(".a-price .a-offscreen")[:5]:
            p = clean_price(el.get_text())
            if p and p > 0:
                prices.append(p)

        new_price = min(prices) if prices else None
        used_price = round(new_price * 0.65, 2) if new_price else None

        return {"new_price": new_price, "used_price": used_price}
