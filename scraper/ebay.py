import httpx
import asyncio
from typing import Dict, Any, Optional
import config
from utils.cache import Cache


APIFY_API_BASE = "https://api.apify.com/v2"
APIFY_ACTOR = "dtrungtin/ebay-items-scraper"


class EbayScraper:
    async def get_sold_data(self, product_name: str, condition: str = "") -> Dict[str, Any]:
        cache_key = f"{product_name}|{condition}"
        cached = await Cache.get("ebay_sold", cache_key)
        if cached:
            return cached

        query = f"{product_name} {condition}".strip()
        result = await self._run_actor(query, sold=True, max_items=40)

        await Cache.set("ebay_sold", cache_key, result, config.CACHE_TTL_EBAY)
        return result

    async def get_active_count(self, product_name: str) -> int:
        cache_key = f"active|{product_name}"
        cached = await Cache.get("ebay_active", cache_key)
        if cached is not None:
            return cached

        result = await self._run_actor(product_name, sold=False, max_items=10)
        count = result.get("count", 0)
        await Cache.set("ebay_active", cache_key, count, config.CACHE_TTL_EBAY)
        return count

    async def _run_actor(self, query: str, sold: bool, max_items: int) -> Dict[str, Any]:
        run_input = {"search": query, "maxItems": max_items, "sold": sold, "startUrls": []}
        token = config.APIFY_API_TOKEN
        actor_id = APIFY_ACTOR.replace("/", "~")

        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                # Trigger actor run
                run_resp = await client.post(
                    f"{APIFY_API_BASE}/acts/{actor_id}/runs?token={token}",
                    json=run_input,
                )
                run_resp.raise_for_status()
                run_data = run_resp.json()
                run_id = run_data["data"]["id"]
                dataset_id = run_data["data"]["defaultDatasetId"]

                # Wait for run to finish (poll)
                for _ in range(30):
                    await asyncio.sleep(3)
                    status_resp = await client.get(
                        f"{APIFY_API_BASE}/actor-runs/{run_id}?token={token}"
                    )
                    status = status_resp.json()["data"]["status"]
                    if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                        break

                if status != "SUCCEEDED":
                    return {"avg": None, "median": None, "min": None, "max": None, "count": 0}

                # Fetch dataset items
                items_resp = await client.get(
                    f"{APIFY_API_BASE}/datasets/{dataset_id}/items?token={token}&limit={max_items}"
                )
                items_resp.raise_for_status()
                items = items_resp.json()

            prices = []
            for item in items:
                price_raw = item.get("price") or item.get("soldPrice") or item.get("priceWithCurrency")
                if price_raw:
                    try:
                        import re
                        cleaned = re.sub(r"[^\d.]", "", str(price_raw).replace(",", ""))
                        if cleaned:
                            prices.append(float(cleaned))
                    except ValueError:
                        pass

            if sold:
                return self._compute_stats(prices)
            else:
                return {"count": len(items)}

        except Exception:
            if sold:
                return {"avg": None, "median": None, "min": None, "max": None, "count": 0}
            return {"count": 0}

    def _compute_stats(self, prices: list) -> Dict[str, Any]:
        if not prices:
            return {"avg": None, "median": None, "min": None, "max": None, "count": 0}
        prices_sorted = sorted(prices)
        n = len(prices_sorted)
        avg = sum(prices_sorted) / n
        median = (
            prices_sorted[n // 2]
            if n % 2 != 0
            else (prices_sorted[n // 2 - 1] + prices_sorted[n // 2]) / 2
        )
        return {
            "avg": round(avg, 2),
            "median": round(median, 2),
            "min": round(prices_sorted[0], 2),
            "max": round(prices_sorted[-1], 2),
            "count": n,
        }
