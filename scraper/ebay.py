import re
import httpx
import asyncio
from typing import Dict, Any
from bs4 import BeautifulSoup
import config
from utils.cache import Cache


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Limit concurrent eBay requests
_semaphore = asyncio.Semaphore(6)


def _proxies() -> dict | None:
    key = getattr(config, "BRIGHTDATA_API_KEY", "")
    zone = getattr(config, "BRIGHTDATA_ZONE", "web_unlocker1")
    if not key:
        return None
    p = f"http://zone-{zone}:{key}@brd.superproxy.io:22225"
    return {"http://": p, "https://": p}


class EbayScraper:
    async def get_sold_data(self, product_name: str, condition: str = "") -> Dict[str, Any]:
        cache_key = f"{product_name}|{condition}"
        cached = await Cache.get("ebay_sold", cache_key)
        if cached:
            return cached

        query = f"{product_name} {condition}".strip()
        result = await self._search_ebay(query, sold=True, max_items=60)

        await Cache.set("ebay_sold", cache_key, result, config.CACHE_TTL_EBAY)
        return result

    async def get_active_count(self, product_name: str) -> int:
        cache_key = f"active|{product_name}"
        cached = await Cache.get("ebay_active", cache_key)
        if cached is not None:
            return cached

        result = await self._search_ebay(product_name, sold=False, max_items=20)
        count = result.get("count", 0)
        await Cache.set("ebay_active", cache_key, count, config.CACHE_TTL_EBAY)
        return count

    async def _search_ebay(self, query: str, sold: bool, max_items: int) -> Dict[str, Any]:
        params: dict = {
            "_nkw": query,
            "_ipg": str(min(max_items, 60)),
            "_sop": "13",
        }
        if sold:
            params["LH_Complete"] = "1"
            params["LH_Sold"] = "1"

        _empty = {"avg": None, "median": None, "min": None, "max": None, "count": 0}
        url = "https://www.ebay.com/sch/i.html"

        async def _fetch(proxies=None) -> str | None:
            try:
                kwargs = {"timeout": 15.0, "follow_redirects": True}
                if proxies:
                    kwargs["proxies"] = proxies
                    kwargs["verify"] = False
                async with httpx.AsyncClient(**kwargs) as client:
                    resp = await client.get(url, params=params, headers=_HEADERS)
                    if resp.status_code == 200 and len(resp.text) > 2000:
                        return resp.text
            except Exception:
                pass
            return None

        try:
            async with _semaphore:
                # Try direct first (fast), fallback to BrightData proxy
                html = await _fetch()
                if not html:
                    html = await _fetch(proxies=_proxies())
                if not html:
                    return _empty if sold else {"count": 0}

            prices = self._parse_prices(html)
            if sold:
                return self._compute_stats(prices)
            return {"count": len(prices)}

        except Exception:
            return _empty if sold else {"count": 0}

    def _parse_prices(self, html: str) -> list:
        soup = BeautifulSoup(html, "lxml")
        prices = []
        for el in soup.select(".s-item__price"):
            text = el.get_text(strip=True)
            # Handle "X to Y" price ranges — take the midpoint
            parts = re.split(r"\s+to\s+", text, flags=re.IGNORECASE)
            nums = []
            for part in parts:
                cleaned = re.sub(r"[^\d.]", "", part.replace(",", ""))
                if cleaned:
                    try:
                        nums.append(float(cleaned))
                    except ValueError:
                        pass
            if nums:
                prices.append(sum(nums) / len(nums))
        return prices

    def _compute_stats(self, prices: list) -> Dict[str, Any]:
        if not prices:
            return {"avg": None, "median": None, "min": None, "max": None, "count": 0}
        s = sorted(prices)
        n = len(s)
        avg = sum(s) / n
        median = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
        return {
            "avg": round(avg, 2),
            "median": round(median, 2),
            "min": round(s[0], 2),
            "max": round(s[-1], 2),
            "count": n,
        }
