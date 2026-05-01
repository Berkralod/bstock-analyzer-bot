import re
import httpx
import asyncio
from typing import Dict, Any
from bs4 import BeautifulSoup
import config
from utils.cache import Cache
from utils.proxy import brightdata_proxies

# eBay Finding API — free, no scraping, <1s per call
_FINDING_API = "https://svcs.ebay.com/services/search/FindingService/v1"
_EBAY_SEARCH = "https://www.ebay.com/sch/i.html"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

_semaphore = asyncio.Semaphore(6)


class EbayScraper:
    async def get_sold_data(self, product_name: str, condition: str = "") -> Dict[str, Any]:
        cache_key = f"ebay|{product_name}|{condition}"
        cached = await Cache.get("ebay_sold", cache_key)
        if cached:
            return cached

        query = f"{product_name} {condition}".strip()
        result = await self._get_prices(query, sold=True)

        if result.get("avg"):
            await Cache.set("ebay_sold", cache_key, result, config.CACHE_TTL_EBAY)
        return result

    async def get_active_count(self, product_name: str) -> int:
        cache_key = f"ebay_active|{product_name}"
        cached = await Cache.get("ebay_active", cache_key)
        if cached is not None:
            return cached
        result = await self._get_prices(product_name, sold=False)
        count = result.get("count", 0)
        await Cache.set("ebay_active", cache_key, count, config.CACHE_TTL_EBAY)
        return count

    async def _get_prices(self, query: str, sold: bool) -> Dict[str, Any]:
        """Try Finding API first, fall back to BrightData scraping."""
        app_id = getattr(config, "EBAY_APP_ID", "")
        if app_id:
            return await self._finding_api(query, sold, app_id)
        return await self._scrape_via_brightdata(query, sold)

    async def _finding_api(self, query: str, sold: bool, app_id: str) -> Dict[str, Any]:
        _empty = {"avg": None, "median": None, "min": None, "max": None, "count": 0}

        if sold:
            operation = "findCompletedItems"
            filters = {
                "itemFilter(0).name": "SoldItemsOnly",
                "itemFilter(0).value": "true",
            }
        else:
            operation = "findItemsByKeywords"
            filters = {}

        params = {
            "OPERATION-NAME": operation,
            "SERVICE-VERSION": "1.0.0",
            "SECURITY-APPNAME": app_id,
            "RESPONSE-DATA-FORMAT": "JSON",
            "keywords": query,
            "sortOrder": "EndTimeSoonest",
            "paginationInput.entriesPerPage": "40",
            **filters,
        }

        try:
            async with _semaphore:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(_FINDING_API, params=params)
                    resp.raise_for_status()
                    data = resp.json()

            if sold:
                return self._parse_completed(data)
            else:
                total = (
                    data.get("findItemsByKeywordsResponse", [{}])[0]
                    .get("paginationOutput", [{}])[0]
                    .get("totalEntries", [0])[0]
                )
                return {"count": int(total)}

        except Exception:
            return _empty if sold else {"count": 0}

    async def _scrape_via_brightdata(self, query: str, sold: bool) -> Dict[str, Any]:
        """Scrape eBay completed listings via BrightData proxy."""
        proxies = brightdata_proxies()
        _empty = {"avg": None, "median": None, "min": None, "max": None, "count": 0}
        if not proxies:
            return _empty if sold else {"count": 0}

        params: dict = {"_nkw": query, "_ipg": "60", "_sop": "13"}
        if sold:
            params["LH_Complete"] = "1"
            params["LH_Sold"] = "1"

        try:
            async with _semaphore:
                timeout = httpx.Timeout(connect=8.0, read=25.0, write=5.0, pool=3.0)
                async with httpx.AsyncClient(
                    proxies=proxies, timeout=timeout, verify=False, follow_redirects=True
                ) as client:
                    resp = await client.get(_EBAY_SEARCH, params=params, headers=_HEADERS)
                    if resp.status_code != 200 or len(resp.text) < 2000:
                        return _empty if sold else {"count": 0}
                    html = resp.text

            prices = self._parse_html_prices(html)
            if sold:
                return self._compute_stats(prices)
            return {"count": len(prices)}
        except Exception:
            return _empty if sold else {"count": 0}

    def _parse_html_prices(self, html: str) -> list:
        soup = BeautifulSoup(html, "lxml")
        prices = []
        for el in soup.select(".s-item__price"):
            text = el.get_text(strip=True)
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

    def _parse_completed(self, data: dict) -> Dict[str, Any]:
        _empty = {"avg": None, "median": None, "min": None, "max": None, "count": 0}
        try:
            items = (
                data.get("findCompletedItemsResponse", [{}])[0]
                .get("searchResult", [{}])[0]
                .get("item", [])
            )
        except Exception:
            return _empty

        prices = []
        for item in items:
            try:
                price_str = (
                    item.get("sellingStatus", [{}])[0]
                    .get("currentPrice", [{}])[0]
                    .get("__value__", "")
                )
                price = float(price_str)
                if price > 0:
                    prices.append(price)
            except Exception:
                continue

        return self._compute_stats(prices)

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
