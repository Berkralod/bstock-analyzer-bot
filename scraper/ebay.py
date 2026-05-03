import re
import time
import httpx
import asyncio
import base64
from typing import Dict, Any, Optional
import config
from utils.cache import Cache

_BROWSE_API = "https://api.ebay.com/buy/browse/v1/item_summary/search"
_INSIGHTS_API = "https://api.ebay.com/buy/marketplace_insights/v1_beta/item_sales/search"
_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
_EBAY_CERT_ID = "PRD-6c21b7a29737-ebe0-43a4-bd70-f269"

_semaphore = asyncio.Semaphore(4)

# In-memory token cache
_token_cache: dict = {"token": None, "expires_at": 0}


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
        token = await self._get_token()
        if not token:
            return {"avg": None, "median": None, "min": None, "max": None, "count": 0}
        # Try sold items endpoint first, fall back to active listings
        if sold:
            result = await self._insights_api(query, token)
            if result.get("avg"):
                return result
            # Fallback: use active listing prices with discount factor
            result = await self._browse_api(query, token)
            if result.get("avg"):
                # Active prices ~15% higher than actual sold prices on average
                avg = result["avg"]
                median = result["median"]
                mn = result["min"]
                mx = result["max"]
                return {
                    "avg": round(avg * 0.85, 2),
                    "median": round(median * 0.85, 2) if median else None,
                    "min": round(mn * 0.85, 2) if mn else None,
                    "max": round(mx * 0.85, 2) if mx else None,
                    "count": result.get("count", 0),
                }
            return result
        else:
            return await self._browse_api(query, token)

    async def _get_token(self) -> Optional[str]:
        app_id = getattr(config, "EBAY_APP_ID", "")
        if not app_id:
            return None

        now = time.time()
        if _token_cache["token"] and _token_cache["expires_at"] > now + 60:
            return _token_cache["token"]

        try:
            creds = base64.b64encode(f"{app_id}:{_EBAY_CERT_ID}".encode()).decode()
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    _TOKEN_URL,
                    headers={
                        "Authorization": f"Basic {creds}",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    data={
                        "grant_type": "client_credentials",
                        "scope": "https://api.ebay.com/oauth/api_scope",
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    _token_cache["token"] = data["access_token"]
                    _token_cache["expires_at"] = now + data.get("expires_in", 7200)
                    return _token_cache["token"]
        except Exception:
            pass
        return None

    async def _insights_api(self, query: str, token: str) -> Dict[str, Any]:
        """Marketplace Insights API — actual sold prices (beta)."""
        _empty: Dict[str, Any] = {"avg": None, "median": None, "min": None, "max": None, "count": 0}
        try:
            async with _semaphore:
                async with httpx.AsyncClient(timeout=12.0) as client:
                    resp = await client.get(
                        _INSIGHTS_API,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
                        },
                        params={"q": query, "limit": "50"},
                    )
                    if resp.status_code != 200:
                        return _empty
                    data = resp.json()

            prices = []
            for item in data.get("itemSales", []):
                try:
                    price = float(item["lastSoldPrice"]["value"])
                    if price > 0:
                        prices.append(price)
                except (KeyError, ValueError, TypeError):
                    continue
            return self._compute_stats(prices)
        except Exception:
            return _empty

    async def _browse_api(self, query: str, token: str) -> Dict[str, Any]:
        """Browse API — active listings (fallback for prices)."""
        _empty: Dict[str, Any] = {"avg": None, "median": None, "min": None, "max": None, "count": 0}
        try:
            async with _semaphore:
                async with httpx.AsyncClient(timeout=12.0) as client:
                    resp = await client.get(
                        _BROWSE_API,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
                        },
                        params={"q": query, "limit": "50", "filter": "buyingOptions:{FIXED_PRICE}"},
                    )
                    if resp.status_code != 200:
                        return _empty
                    data = resp.json()

            prices = []
            for item in data.get("itemSummaries", []):
                try:
                    price = float(item["price"]["value"])
                    if price > 0:
                        prices.append(price)
                except (KeyError, ValueError, TypeError):
                    continue
            return self._compute_stats(prices)
        except Exception:
            return _empty

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
