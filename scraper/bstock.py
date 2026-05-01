import httpx
import re
import json
from bs4 import BeautifulSoup
import config
from models.lot import Lot
from models.product import Product
from utils.helpers import clean_price, normalize_condition, extract_lot_id
from utils.haiku import HaikuClient

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

LOGIN_URL = "https://bstock.com/api/auth/login"
BSTOCK_HOME = "https://bstock.com"

# Real B-Stock microservice URLs (from __NEXT_DATA__ hostMap)
AUTH_BASE = "https://auth.bstock.com"
LISTING_BASE = "https://listing.bstock.com"
AUCTION_BASE = "https://auction.bstock.com"
FA_APPLICATION_ID = "1b094c5f-c8a6-416c-8c62-4dc77ca88ce9"

LISTING_PATTERNS = [
    f"{LISTING_BASE}/v1/listings/{{uid}}",
    f"{LISTING_BASE}/v1/listings/{{uid}}/details",
    f"{AUCTION_BASE}/v1/auctions/{{uid}}",
]


def _bright_data_proxies() -> dict | None:
    key = getattr(config, "BRIGHTDATA_API_KEY", "")
    zone = getattr(config, "BRIGHTDATA_ZONE", "web_unlocker1")
    if not key:
        return None
    p = f"http://zone-{zone}:{key}@brd.superproxy.io:22225"
    return {"http://": p, "https://": p}


class BStockScraper:
    def __init__(self) -> None:
        self._haiku = HaikuClient()
        self._cookies: dict = {}
        self._auth_token: str = ""

    async def _login(self, client: httpx.AsyncClient) -> bool:
        email = getattr(config, "BSTOCK_EMAIL", "")
        password = getattr(config, "BSTOCK_PASSWORD", "")
        if not email or not password:
            return False

        # FusionAuth /api/login with applicationId (resolves TenantIdRequired)
        try:
            resp = await client.post(
                f"{AUTH_BASE}/api/login",
                json={
                    "loginId": email,
                    "password": password,
                    "applicationId": FA_APPLICATION_ID,
                },
                headers={**HEADERS, "Content-Type": "application/json"},
                timeout=12.0,
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                token = data.get("token") or (data.get("user") or {}).get("token")
                if token:
                    self._auth_token = token
                    self._cookies = dict(client.cookies)
                    return True
        except Exception:
            pass

        return False

    def _auth_headers(self) -> dict:
        h = dict(HEADERS)
        if self._auth_token:
            h["Authorization"] = f"Bearer {self._auth_token}"
        return h

    async def _try_json_api(self, uid: str, client: httpx.AsyncClient) -> dict | None:
        """
        B-Stock API flow (discovered via debug):
        1. GET listing.bstock.com/v1/listings/{uid} → listing metadata + lotId
        2. GET offering.bstock.com/v1/offerings?listingId={uid} → offerings with products
        """
        headers = {**self._auth_headers(), "Accept": "application/json"}

        # Step 1: Get listing metadata
        listing_data = None
        try:
            r = await client.get(
                f"{LISTING_BASE}/v1/listings/{uid}",
                headers=headers,
                timeout=12.0,
            )
            if r.status_code == 200:
                listing_data = r.json()
        except Exception:
            pass

        # Step 2: Get offerings (contains products)
        try:
            r = await client.get(
                f"https://offering.bstock.com/v1/offerings?listingId={uid}",
                headers=headers,
                timeout=12.0,
            )
            if r.status_code == 200:
                data = r.json()
                offerings = data.get("offerings", [])
                if offerings and listing_data:
                    # Merge listing metadata with offering product data
                    result = dict(listing_data)
                    result["offerings"] = offerings
                    # Flatten first offering's items to top-level products
                    for offering in offerings:
                        items = (
                            offering.get("items")
                            or offering.get("products")
                            or offering.get("lots")
                            or offering.get("manifest")
                            or []
                        )
                        if items:
                            result["products"] = items
                            break
                    return result
                elif offerings:
                    return {"offerings": offerings}
        except Exception:
            pass

        # Return listing metadata alone (will trigger Haiku fallback)
        if listing_data:
            return listing_data

        return None

    async def _fetch_url(self, url: str) -> tuple[str, dict | None]:
        """Returns (html, json_data). json_data takes priority if not None."""
        uid = extract_lot_id(url)

        # 1. Try with existing cookies + JSON API
        if self._cookies or self._auth_token:
            try:
                async with httpx.AsyncClient(
                    timeout=25.0, follow_redirects=True, cookies=self._cookies
                ) as client:
                    if uid:
                        data = await self._try_json_api(uid, client)
                        if data:
                            return "", data
                    resp = await client.get(url, headers=HEADERS)
                    if resp.status_code == 200 and len(resp.text) > 1000:
                        return resp.text, None
            except Exception:
                pass

        # 2. Fresh login session
        email = getattr(config, "BSTOCK_EMAIL", "")
        if email:
            try:
                async with httpx.AsyncClient(
                    timeout=35.0, follow_redirects=True
                ) as client:
                    logged_in = await self._login(client)
                    if logged_in and uid:
                        data = await self._try_json_api(uid, client)
                        if data:
                            return "", data
                    resp = await client.get(url, headers=self._auth_headers())
                    if resp.status_code == 200 and len(resp.text) > 1000:
                        return resp.text, None
            except Exception:
                pass

        # 3. Bright Data Web Unlocker proxy (renders JS, bypasses blocks)
        proxies = _bright_data_proxies()
        if proxies:
            try:
                async with httpx.AsyncClient(
                    proxies=proxies, timeout=35.0, follow_redirects=True, verify=False
                ) as client:
                    if email:
                        await self._login(client)
                    if uid:
                        data = await self._try_json_api(uid, client)
                        if data:
                            return "", data
                    resp = await client.get(url, headers=self._auth_headers())
                    if resp.status_code == 200:
                        return resp.text, None
            except Exception as e:
                raise RuntimeError(f"Bright Data proxy hatası: {e}")

        raise RuntimeError(
            "Sayfa alınamadı. B-Stock girişi gerekiyor — "
            "/credentials komutuyla email ve şifreni gir."
        )

    async def scrape_lot(self, url: str) -> Lot:
        html, json_data = await self._fetch_url(url)
        lot = await self._parse(url, html, json_data)
        lot.compute_totals()
        return lot

    @staticmethod
    def _extract_next_data(html: str) -> str | None:
        """Pull raw __NEXT_DATA__ JSON string out of HTML."""
        start = html.find('"__NEXT_DATA__"')
        if start == -1:
            start = html.find("id=\"__NEXT_DATA__\"")
            if start == -1:
                return None
        # Find the script tag content
        brace = html.find("{", start)
        if brace == -1:
            return None
        depth, i = 0, brace
        while i < len(html):
            if html[i] == "{":
                depth += 1
            elif html[i] == "}":
                depth -= 1
                if depth == 0:
                    return html[brace:i + 1]
            i += 1
        return None

    def _apply_parsed(self, parsed: dict, lot: Lot, products: list) -> list:
        lot.title = lot.title or parsed.get("title")
        lot.current_bid = lot.current_bid or parsed.get("current_bid")
        lot.shipping_cost = lot.shipping_cost or parsed.get("shipping_cost")
        if parsed.get("buyers_premium_rate"):
            lot.buyers_premium_rate = parsed["buyers_premium_rate"]
        lot.manifest_url = lot.manifest_url or parsed.get("manifest_url")
        result = list(products)
        for p_data in parsed.get("products", []):
            result.append(Product(
                name=p_data.get("name", "Unknown"),
                condition=normalize_condition(p_data.get("condition", "")),
                quantity=int(p_data.get("quantity") or 1),
                listed_msrp=clean_price(str(p_data.get("msrp", "") or "")),
            ))
        return result

    async def _parse(self, url: str, html: str, json_data: dict | None) -> Lot:
        lot = Lot(url=url, lot_id=extract_lot_id(url))

        if json_data:
            products = self._parse_json(json_data, lot)
            if products:
                lot.products = products
                return lot

        if html:
            soup = BeautifulSoup(html, "lxml")
            products = self._parse_structured(soup, lot)

            if len(products) < 2:
                # Try __NEXT_DATA__ via Haiku (targeted — not raw 118k HTML)
                next_data_str = self._extract_next_data(html)
                if next_data_str:
                    try:
                        parsed = await self._haiku.parse_bstock_next_data(next_data_str)
                        if parsed.get("products"):
                            products = self._apply_parsed(parsed, lot, products)
                    except Exception:
                        pass

            if len(products) < 2:
                # Final fallback: Haiku on first 8k of raw HTML
                try:
                    parsed = await self._haiku.parse_bstock_html(html)
                    if parsed.get("products"):
                        products = self._apply_parsed(parsed, lot, products)
                except Exception:
                    pass

            lot.products = products

        return lot

    def _parse_json(self, data: dict, lot: Lot) -> list:
        """Parse B-Stock listing/offering API JSON response."""
        products = []

        # Extract listing-level metadata
        lot.lot_id = lot.lot_id or data.get("prettyId") or data.get("formattedPrettyId")

        shipping = data.get("shipping") or {}
        if isinstance(shipping, dict):
            cost = shipping.get("cost") or shipping.get("price") or shipping.get("amount")
            if cost:
                lot.shipping_cost = lot.shipping_cost or clean_price(str(cost))

        # pricingStrategy → look for current bid in saleMetrics
        sale_metrics = data.get("saleMetrics") or {}
        if isinstance(sale_metrics, dict):
            bid = (
                sale_metrics.get("currentBid")
                or sale_metrics.get("current_bid")
                or sale_metrics.get("highBid")
            )
            lot.current_bid = lot.current_bid or clean_price(str(bid or ""))

        # Offerings → products
        for offering in (data.get("offerings") or []):
            if not isinstance(offering, dict):
                continue
            # Offering may have title, shipping, premium
            lot.title = lot.title or offering.get("title") or offering.get("name")
            premium = offering.get("buyersPremium") or offering.get("buyerPremium")
            if premium:
                try:
                    rate = float(str(premium).replace("%", "").strip())
                    lot.buyers_premium_rate = rate / 100 if rate > 1 else rate
                except Exception:
                    pass

            items = (
                offering.get("items") or offering.get("products")
                or offering.get("manifest") or offering.get("lots") or []
            )
            for item in items:
                p = self._item_to_product(item)
                if p:
                    products.append(p)

        # Direct products list
        for item in (data.get("products") or []):
            p = self._item_to_product(item)
            if p:
                products.append(p)

        return products

    def _item_to_product(self, item: dict) -> Product | None:
        if not isinstance(item, dict):
            return None
        name = (
            item.get("productName") or item.get("name") or item.get("title")
            or item.get("description") or ""
        )
        if not name or len(name) < 3:
            return None
        condition_text = (
            item.get("condition") or item.get("conditionName") or item.get("grade") or ""
        )
        qty = 1
        for qk in ("quantity", "qty", "count", "units"):
            if item.get(qk):
                try:
                    qty = int(item[qk])
                    break
                except Exception:
                    pass
        msrp_raw = (
            item.get("msrp") or item.get("retailPrice") or item.get("retail_price")
            or item.get("listPrice") or ""
        )
        return Product(
            name=name,
            condition=normalize_condition(condition_text),
            quantity=qty,
            listed_msrp=clean_price(str(msrp_raw)),
        )

    def _parse_structured(self, soup: BeautifulSoup, lot: Lot) -> list:
        products = []

        for sel in ["h1.lot-title", ".lot-header h1", "[data-testid='lot-title']",
                    "h1[class*='title']", ".listing-title", "h1"]:
            el = soup.select_one(sel)
            if el and len(el.get_text(strip=True)) > 3:
                lot.title = el.get_text(strip=True)
                break

        for sel in [".current-bid", ".bid-amount", "[data-testid='current-bid']",
                    "[class*='currentBid']", "[class*='current_bid']", "[class*='bid-price']"]:
            el = soup.select_one(sel)
            if el:
                lot.current_bid = clean_price(el.get_text())
                break

        for sel in [".shipping-cost", ".freight-cost", "[class*='shipping']", "[class*='freight']"]:
            el = soup.select_one(sel)
            if el:
                lot.shipping_cost = clean_price(el.get_text())
                break

        for sel in [".buyers-premium", "[class*='premium']", "[class*='buyer']"]:
            el = soup.select_one(sel)
            if el:
                m = re.search(r"(\d+(?:\.\d+)?)\s*%", el.get_text())
                if m:
                    lot.buyers_premium_rate = float(m.group(1)) / 100
                break

        manifest = soup.select_one("a[href*='manifest'], a[href*='.csv'], a[href*='.pdf']")
        if manifest:
            lot.manifest_url = manifest.get("href")

        # Extract JSON from Next.js __NEXT_DATA__ or window.__STATE__
        for script in soup.find_all("script", {"id": "__NEXT_DATA__"}):
            try:
                next_data = json.loads(script.string)
                page_props = (
                    next_data.get("props", {}).get("pageProps", {})
                )
                # Try to find listing/auction data in pageProps
                for key in ("listing", "auction", "lot", "data", "initialData"):
                    val = page_props.get(key)
                    if isinstance(val, dict):
                        parsed_products = self._parse_json(val, lot)
                        if parsed_products:
                            return parsed_products
                # Also try top-level dehydratedState (React Query)
                dehydrated = page_props.get("dehydratedState") or {}
                for query in (dehydrated.get("queries") or []):
                    qdata = (query.get("state") or {}).get("data") or {}
                    if isinstance(qdata, dict):
                        parsed_products = self._parse_json(qdata, lot)
                        if parsed_products:
                            return parsed_products
            except Exception:
                pass

        row_selectors = [
            ".manifest-row", ".product-row", ".item-row",
            "table tbody tr", "[class*='manifest'] tr",
            "[class*='item-list'] li", "[class*='lot-item']",
        ]
        for sel in row_selectors:
            rows = soup.select(sel)
            if not rows:
                continue
            for row in rows:
                cells = row.select("td, .cell, [class*='col']")
                if len(cells) < 2:
                    continue
                name_el = row.select_one(
                    ".item-name, .product-name, [class*='name'], td:first-child"
                )
                if not name_el:
                    continue
                name = name_el.get_text(strip=True)
                if not name or len(name) < 3:
                    continue
                cond_el = row.select_one(".condition, [class*='condition'], td:nth-child(2)")
                condition_text = cond_el.get_text(strip=True) if cond_el else ""
                qty_el = row.select_one(".quantity, [class*='qty'], td:nth-child(3)")
                try:
                    qty = int((qty_el.get_text(strip=True) if qty_el else "1").replace(",", ""))
                except ValueError:
                    qty = 1
                msrp_el = row.select_one(".msrp, .retail-price, [class*='msrp'], td:nth-child(4)")
                msrp = clean_price(msrp_el.get_text() if msrp_el else "")
                products.append(Product(
                    name=name,
                    condition=normalize_condition(condition_text),
                    quantity=qty,
                    listed_msrp=msrp,
                ))
            if products:
                break

        return products
