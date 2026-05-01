import re
import httpx
import asyncio
from typing import Dict, Any
import config
from utils.cache import Cache

# eBay Finding API — free, no scraping, <1s per call
_FINDING_API = "https://svcs.ebay.com/services/search/FindingService/v1"

_semaphore = asyncio.Semaphore(8)


class EbayScraper:
    async def get_sold_data(self, product_name: str, condition: str = "") -> Dict[str, Any]:
        cache_key = f"ebay|{product_name}|{condition}"
        cached = await Cache.get("ebay_sold", cache_key)
        if cached:
            return cached

        query = f"{product_name} {condition}".strip()
        result = await self._finding_api(query, sold=True)

        if result.get("avg"):
            await Cache.set("ebay_sold", cache_key, result, config.CACHE_TTL_EBAY)
        return result

    async def get_active_count(self, product_name: str) -> int:
        cache_key = f"ebay_active|{product_name}"
        cached = await Cache.get("ebay_active", cache_key)
        if cached is not None:
            return cached
        result = await self._finding_api(product_name, sold=False)
        count = result.get("count", 0)
        await Cache.set("ebay_active", cache_key, count, config.CACHE_TTL_EBAY)
        return count

    async def _finding_api(self, query: str, sold: bool) -> Dict[str, Any]:
        app_id = getattr(config, "EBAY_APP_ID", "")
        _empty = {"avg": None, "median": None, "min": None, "max": None, "count": 0}

        if not app_id:
            return _empty if sold else {"count": 0}

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
