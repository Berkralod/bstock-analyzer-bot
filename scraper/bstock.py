import httpx
import re
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
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://bstock.com/",
}

# Bright Data proxy format using zone password (no customer ID needed with this format)
def _bright_data_proxies() -> dict | None:
    key = getattr(config, "BRIGHTDATA_API_KEY", "")
    zone = getattr(config, "BRIGHTDATA_ZONE", "web_unlocker1")
    if not key:
        return None
    proxy_url = f"http://zone-{zone}:{key}@brd.superproxy.io:22225"
    return {"http://": proxy_url, "https://": proxy_url}


class BStockScraper:
    def __init__(self) -> None:
        self._haiku = HaikuClient()

    async def _fetch_url(self, url: str) -> str:
        # 1. Try direct request first
        try:
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                resp = await client.get(url, headers=HEADERS)
                if resp.status_code == 200 and len(resp.text) > 500:
                    return resp.text
        except Exception:
            pass

        # 2. Fallback: Bright Data proxy
        proxies = _bright_data_proxies()
        if proxies:
            try:
                async with httpx.AsyncClient(
                    proxies=proxies, timeout=30.0, follow_redirects=True, verify=False
                ) as client:
                    resp = await client.get(url, headers=HEADERS)
                    resp.raise_for_status()
                    return resp.text
            except Exception as e:
                raise RuntimeError(f"Bright Data proxy error: {e}")

        raise RuntimeError("Could not fetch URL: direct request failed and Bright Data not configured")

    async def scrape_lot(self, url: str) -> Lot:
        html = await self._fetch_url(url)
        lot = await self._parse_html(url, html)
        lot.compute_totals()
        return lot

    async def _parse_html(self, url: str, html: str) -> Lot:
        soup = BeautifulSoup(html, "lxml")
        lot = Lot(url=url, lot_id=extract_lot_id(url))

        products = self._parse_structured(soup, lot)

        if not products:
            # AI fallback
            parsed = await self._haiku.parse_bstock_html(html)
            lot.title = parsed.get("title")
            lot.current_bid = parsed.get("current_bid")
            lot.shipping_cost = parsed.get("shipping_cost")
            if parsed.get("buyers_premium_rate"):
                lot.buyers_premium_rate = parsed["buyers_premium_rate"]
            lot.manifest_url = parsed.get("manifest_url")
            for p_data in parsed.get("products", []):
                products.append(
                    Product(
                        name=p_data.get("name", "Unknown"),
                        condition=normalize_condition(p_data.get("condition", "")),
                        quantity=int(p_data.get("quantity", 1)),
                        listed_msrp=clean_price(str(p_data.get("msrp", "") or "")),
                    )
                )

        lot.products = products
        return lot

    def _parse_structured(self, soup: BeautifulSoup, lot: Lot) -> list:
        products = []

        # Title
        for sel in ["h1.lot-title", ".lot-header h1", "[data-testid='lot-title']", "h1"]:
            el = soup.select_one(sel)
            if el:
                lot.title = el.get_text(strip=True)
                break

        # Current bid
        for sel in [".current-bid", ".bid-amount", "[data-testid='current-bid']",
                    "[class*='currentBid']", "[class*='current_bid']"]:
            el = soup.select_one(sel)
            if el:
                lot.current_bid = clean_price(el.get_text())
                break

        # Shipping
        for sel in [".shipping-cost", ".freight-cost", "[data-testid='shipping']",
                    "[class*='shipping']", "[class*='freight']"]:
            el = soup.select_one(sel)
            if el:
                lot.shipping_cost = clean_price(el.get_text())
                break

        # Buyer's premium
        for sel in [".buyers-premium", "[data-testid='buyers-premium']", "[class*='premium']"]:
            el = soup.select_one(sel)
            if el:
                m = re.search(r"(\d+(?:\.\d+)?)\s*%", el.get_text())
                if m:
                    lot.buyers_premium_rate = float(m.group(1)) / 100
                break

        # Manifest link
        manifest = soup.select_one("a[href*='manifest'], a[href*='.csv'], a[href*='.pdf']")
        if manifest:
            lot.manifest_url = manifest.get("href")

        # Product rows
        rows = soup.select(".manifest-row, .product-row, table tbody tr, .item-list-row, [class*='manifest'] tr")
        for row in rows:
            cells = row.select("td, .cell")
            if len(cells) < 2:
                continue
            name_el = row.select_one(".item-name, .product-name, td:first-child")
            if not name_el:
                continue
            name = name_el.get_text(strip=True)
            if not name or len(name) < 3:
                continue

            cond_el = row.select_one(".condition, td:nth-child(2)")
            condition_text = cond_el.get_text(strip=True) if cond_el else ""
            qty_el = row.select_one(".quantity, td:nth-child(3)")
            try:
                qty = int((qty_el.get_text(strip=True) if qty_el else "1").replace(",", ""))
            except ValueError:
                qty = 1
            msrp_el = row.select_one(".msrp, .retail-price, td:nth-child(4)")
            msrp = clean_price(msrp_el.get_text() if msrp_el else "")

            products.append(Product(
                name=name,
                condition=normalize_condition(condition_text),
                quantity=qty,
                listed_msrp=msrp,
            ))

        return products
