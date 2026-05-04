import time
import httpx
import asyncio
import base64
from typing import Dict, Any, Optional
import config
from utils.cache import Cache

_BROWSE_API = "https://api.ebay.com/buy/browse/v1/item_summary/search"
_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
_EBAY_CERT_ID = "PRD-6c21b7a29737-ebe0-43a4-bd70-f269"

_token_cache: dict = {"token": None, "expires_at": 0}
_token_lock: asyncio.Lock | None = None
_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(8)
    return _semaphore


def _get_lock() -> asyncio.Lock:
    global _token_lock
    if _token_lock is None:
        _token_lock = asyncio.Lock()
    return _token_lock


class EbayScraper:
    async def get_sold_data(
        self, product_name: str, condition: str = "", msrp: float | None = None
    ) -> Dict[str, Any]:
        cache_key = f"ebay|{product_name}|{condition}"
        cached = await Cache.get("ebay_sold", cache_key)
        if cached:
            return cached

        query = f"{product_name} {condition}".strip()
        result = await self._fetch_prices(query, msrp=msrp)

        if result.get("avg"):
            await Cache.set("ebay_sold", cache_key, result, config.CACHE_TTL_EBAY)
        return result

    async def get_active_count(self, product_name: str) -> int:
        cache_key = f"ebay_active|{product_name}"
        cached = await Cache.get("ebay_active", cache_key)
        if cached is not None:
            return cached
        result = await self._fetch_prices(product_name)
        count = result.get("count", 0)
        await Cache.set("ebay_active", cache_key, count, config.CACHE_TTL_EBAY)
        return count

    async def _fetch_prices(self, query: str, msrp: float | None = None) -> Dict[str, Any]:
        """Fetch prices via Browse API. Apply 0.85 factor to estimate sold prices."""
        _empty: Dict[str, Any] = {"avg": None, "median": None, "min": None, "max": None, "count": 0}
        token = await self._get_token()
        if not token:
            return _empty

        try:
            async with _get_semaphore():
                async with httpx.AsyncClient(timeout=10.0) as client:
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

            # Filter out outliers using MSRP ceiling (5x) and IQR
            if msrp and msrp > 0:
                ceiling = msrp * 5
                prices = [p for p in prices if p <= ceiling]

            prices = self._iqr_filter(prices)

            stats = self._compute_stats(prices)
            # Active listing prices are ~15% higher than actual sold — apply discount
            if stats.get("avg"):
                return {
                    "avg": round(stats["avg"] * 0.85, 2),
                    "median": round(stats["median"] * 0.85, 2) if stats["median"] else None,
                    "min": round(stats["min"] * 0.85, 2) if stats["min"] else None,
                    "max": round(stats["max"] * 0.85, 2) if stats["max"] else None,
                    "count": stats["count"],
                }
            return _empty
        except Exception:
            return _empty

    async def _get_token(self) -> Optional[str]:
        app_id = getattr(config, "EBAY_APP_ID", "")
        if not app_id:
            return None

        now = time.time()
        if _token_cache["token"] and _token_cache["expires_at"] > now + 60:
            return _token_cache["token"]

        async with _get_lock():
            # Re-check inside lock to avoid multiple fetches
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

    def _iqr_filter(self, prices: list) -> list:
        """Remove outliers outside 1.5×IQR. Needs at least 4 data points."""
        if len(prices) < 4:
            return prices
        s = sorted(prices)
        n = len(s)
        q1 = s[n // 4]
        q3 = s[(3 * n) // 4]
        iqr = q3 - q1
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        filtered = [p for p in s if lo <= p <= hi]
        return filtered if filtered else prices

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
