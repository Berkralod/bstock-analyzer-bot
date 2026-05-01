import httpx
from bs4 import BeautifulSoup
import re
import config
from models.lot import Lot
from models.product import Product
from utils.helpers import clean_price, normalize_condition, extract_lot_id
from utils.haiku import HaikuClient


BRIGHTDATA_API_URL = "https://api.brightdata.com/request"


class BStockScraper:
    def __init__(self) -> None:
        self._haiku = HaikuClient()

    async def _fetch_url(self, url: str) -> str:
        """Fetch URL via Bright Data Web Unlocker API."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                BRIGHTDATA_API_URL,
                headers={
                    "Authorization": f"Bearer {config.BRIGHTDATA_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={"zone": config.BRIGHTDATA_ZONE, "url": url, "format": "raw"},
            )
            resp.raise_for_status()
            return resp.text

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

        title_el = soup.select_one("h1.lot-title, .lot-header h1, [data-testid='lot-title']")
        if title_el:
            lot.title = title_el.get_text(strip=True)

        bid_el = soup.select_one(".current-bid, .bid-amount, [data-testid='current-bid']")
        if bid_el:
            lot.current_bid = clean_price(bid_el.get_text())

        ship_el = soup.select_one(".shipping-cost, .freight-cost, [data-testid='shipping']")
        if ship_el:
            lot.shipping_cost = clean_price(ship_el.get_text())

        premium_el = soup.select_one(".buyers-premium, [data-testid='buyers-premium']")
        if premium_el:
            text = premium_el.get_text()
            m = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
            if m:
                lot.buyers_premium_rate = float(m.group(1)) / 100

        manifest_link = soup.select_one("a[href*='manifest'], a[href*='.csv'], a[href*='.pdf']")
        if manifest_link:
            lot.manifest_url = manifest_link.get("href")

        rows = soup.select(".manifest-row, .product-row, table tbody tr, .item-list-row")
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
            qty_text = qty_el.get_text(strip=True) if qty_el else "1"
            try:
                qty = int(qty_text.replace(",", ""))
            except ValueError:
                qty = 1

            msrp_el = row.select_one(".msrp, .retail-price, td:nth-child(4)")
            msrp = clean_price(msrp_el.get_text() if msrp_el else "")

            products.append(
                Product(
                    name=name,
                    condition=normalize_condition(condition_text),
                    quantity=qty,
                    listed_msrp=msrp,
                )
            )

        return products
