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
}

LOGIN_URL = "https://bstock.com/api/auth/login"
BSTOCK_HOME = "https://bstock.com"


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

    async def _login(self, client: httpx.AsyncClient) -> bool:
        email = getattr(config, "BSTOCK_EMAIL", "")
        password = getattr(config, "BSTOCK_PASSWORD", "")
        if not email or not password:
            return False
        try:
            # Get CSRF / session cookie first
            await client.get(BSTOCK_HOME, headers=HEADERS)
            resp = await client.post(
                LOGIN_URL,
                json={"email": email, "password": password},
                headers={**HEADERS, "Content-Type": "application/json",
                         "Referer": "https://bstock.com/login"},
            )
            if resp.status_code in (200, 201, 302):
                self._cookies = dict(client.cookies)
                return True
            # Try form-based login as fallback
            resp2 = await client.post(
                "https://bstock.com/login",
                data={"email": email, "password": password},
                headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
                follow_redirects=True,
            )
            if resp2.status_code == 200 and "logout" in resp2.text.lower():
                self._cookies = dict(client.cookies)
                return True
        except Exception:
            pass
        return False

    async def _fetch_url(self, url: str) -> str:
        # Try with existing cookies first (already logged in)
        try:
            async with httpx.AsyncClient(
                timeout=25.0, follow_redirects=True, cookies=self._cookies
            ) as client:
                resp = await client.get(url, headers=HEADERS)
                if resp.status_code == 200 and len(resp.text) > 1000:
                    return resp.text
        except Exception:
            pass

        # Try fresh session with login
        email = getattr(config, "BSTOCK_EMAIL", "")
        if email:
            try:
                async with httpx.AsyncClient(
                    timeout=30.0, follow_redirects=True
                ) as client:
                    logged_in = await self._login(client)
                    resp = await client.get(url, headers=HEADERS)
                    if resp.status_code == 200 and len(resp.text) > 1000:
                        return resp.text
            except Exception:
                pass

        # Fallback: Bright Data proxy
        proxies = _bright_data_proxies()
        if proxies:
            try:
                async with httpx.AsyncClient(
                    proxies=proxies, timeout=30.0, follow_redirects=True, verify=False
                ) as client:
                    if email:
                        await self._login(client)
                    resp = await client.get(url, headers=HEADERS)
                    if resp.status_code == 200:
                        return resp.text
            except Exception as e:
                raise RuntimeError(f"Bright Data proxy hatası: {e}")

        raise RuntimeError(
            "Sayfa alınamadı. B-Stock girişi gerekiyor — "
            "/credentials komutuyla email ve şifreni gir."
        )

    async def scrape_lot(self, url: str) -> Lot:
        html = await self._fetch_url(url)
        lot = await self._parse_html(url, html)
        lot.compute_totals()
        return lot

    async def _parse_html(self, url: str, html: str) -> Lot:
        soup = BeautifulSoup(html, "lxml")
        lot = Lot(url=url, lot_id=extract_lot_id(url))

        products = self._parse_structured(soup, lot)

        # Always try Haiku if structured parse finds <2 products
        if len(products) < 2:
            try:
                parsed = await self._haiku.parse_bstock_html(html)
                if parsed.get("products"):
                    lot.title = lot.title or parsed.get("title")
                    lot.current_bid = lot.current_bid or parsed.get("current_bid")
                    lot.shipping_cost = lot.shipping_cost or parsed.get("shipping_cost")
                    if not products:
                        if parsed.get("buyers_premium_rate"):
                            lot.buyers_premium_rate = parsed["buyers_premium_rate"]
                        lot.manifest_url = parsed.get("manifest_url")
                        for p_data in parsed.get("products", []):
                            products.append(Product(
                                name=p_data.get("name", "Unknown"),
                                condition=normalize_condition(p_data.get("condition", "")),
                                quantity=int(p_data.get("quantity", 1)),
                                listed_msrp=clean_price(str(p_data.get("msrp", "") or "")),
                            ))
            except Exception:
                pass

        lot.products = products
        return lot

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

        # Broader row selectors
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
