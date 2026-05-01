import asyncio
from typing import Optional, Dict, Any
from apify_client import ApifyClientAsync
import config
from utils.cache import Cache


class EbayScraper:
    def __init__(self) -> None:
        self._client = ApifyClientAsync(config.APIFY_API_TOKEN)

    async def get_sold_data(self, product_name: str, condition: str = "") -> Dict[str, Any]:
        cache_key = f"{product_name}|{condition}"
        cached = await Cache.get("ebay_sold", cache_key)
        if cached:
            return cached

        query = f"{product_name} {condition}".strip()
        run_input = {
            "search": query,
            "maxItems": 40,
            "sold": True,
            "startUrls": [],
        }

        try:
            run = await self._client.actor(config.APIFY_EBAY_ACTOR).call(run_input=run_input)
            items = []
            async for item in self._client.dataset(run["defaultDatasetId"]).iterate_items():
                price = item.get("price") or item.get("soldPrice")
                if price:
                    try:
                        items.append(float(str(price).replace("$", "").replace(",", "")))
                    except ValueError:
                        pass

            result = self._compute_stats(items)
        except Exception:
            result = {"avg": None, "median": None, "min": None, "max": None, "count": 0}

        await Cache.set("ebay_sold", cache_key, result, config.CACHE_TTL_EBAY)
        return result

    async def get_active_count(self, product_name: str) -> int:
        cache_key = f"active|{product_name}"
        cached = await Cache.get("ebay_active", cache_key)
        if cached is not None:
            return cached

        run_input = {
            "search": product_name,
            "maxItems": 10,
            "sold": False,
            "startUrls": [],
        }

        try:
            run = await self._client.actor(config.APIFY_EBAY_ACTOR).call(run_input=run_input)
            count = 0
            async for _ in self._client.dataset(run["defaultDatasetId"]).iterate_items():
                count += 1
        except Exception:
            count = 0

        await Cache.set("ebay_active", cache_key, count, config.CACHE_TTL_EBAY)
        return count

    def _compute_stats(self, prices: list) -> Dict[str, Any]:
        if not prices:
            return {"avg": None, "median": None, "min": None, "max": None, "count": 0}
        prices_sorted = sorted(prices)
        n = len(prices_sorted)
        avg = sum(prices_sorted) / n
        median = prices_sorted[n // 2] if n % 2 != 0 else (prices_sorted[n // 2 - 1] + prices_sorted[n // 2]) / 2
        return {
            "avg": round(avg, 2),
            "median": round(median, 2),
            "min": round(prices_sorted[0], 2),
            "max": round(prices_sorted[-1], 2),
            "count": n,
        }
