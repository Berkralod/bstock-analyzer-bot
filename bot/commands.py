import re
import httpx
from telegram import Update
from telegram.ext import ContextTypes
import config
from scraper.bstock import BStockScraper, HEADERS, LOGIN_URL, BSTOCK_HOME
from analyzer.pipeline import AnalysisPipeline
from bot.formatter import format_report
from utils.cache import Cache
from utils.helpers import extract_lot_id


BSTOCK_URL_PATTERN = re.compile(r"https?://[^\s]*b-?stock[^\s]*", re.IGNORECASE)

_scraper = BStockScraper()
_pipeline = AnalysisPipeline()

# Simple rate limiter per user
_rate_tracker: dict[int, list] = {}
_processing: set[int] = set()  # message_id deduplication
import time


def _check_rate_limit(user_id: int) -> bool:
    now = time.time()
    timestamps = _rate_tracker.get(user_id, [])
    timestamps = [t for t in timestamps if now - t < 60]
    if len(timestamps) >= config.MAX_ANALYSES_PER_MINUTE:
        _rate_tracker[user_id] = timestamps
        return False
    timestamps.append(now)
    _rate_tracker[user_id] = timestamps
    return True


def _is_allowed(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else None
    if not config.ALLOWED_USERS:
        return True
    return uid in config.ALLOWED_USERS


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    await update.message.reply_text(
        "👋 Merhaba! B-Stock Lot Analyzer Bot'a hoşgeldin.\n\n"
        "B-Stock lot linkini direkt gönder veya /analyze <link> kullan.\n"
        "/help için yardım al."
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return
    await update.message.reply_text(
        "📖 *Kullanım*\n\n"
        "• B-Stock lot linkini direkt at → analiz başlar\n"
        "• /analyze <link> → analiz başlat\n"
        "• /history → son 10 analiz\n"
        "• /status → bot durumu\n\n"
        "⏱ Analiz ~1-2 dakika sürebilir.",
        parse_mode="Markdown",
    )


async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return

    text = " ".join(context.args) if context.args else ""
    url_match = BSTOCK_URL_PATTERN.search(text)
    if not url_match:
        await update.message.reply_text("❌ Geçerli bir B-Stock URL'si giriniz.")
        return

    await _run_analysis(update, url_match.group(0))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return

    text = update.message.text or ""
    url_match = BSTOCK_URL_PATTERN.search(text)
    if url_match:
        await _run_analysis(update, url_match.group(0))


async def _run_analysis(update: Update, url: str) -> None:
    user_id = update.effective_user.id
    msg_id = update.message.message_id

    # Deduplicate: Telegram retries webhook if no 200 within 60s
    if msg_id in _processing:
        return
    _processing.add(msg_id)

    if not _check_rate_limit(user_id):
        _processing.discard(msg_id)
        await update.message.reply_text("⏳ Çok hızlı! Dakikada en fazla 5 analiz yapılabilir.")
        return

    msg = await update.message.reply_text("🔍 Lot scrape ediliyor...")

    try:
        import asyncio as _asyncio
        t0 = time.time()

        try:
            lot = await _asyncio.wait_for(_scraper.scrape_lot(url), timeout=60.0)
        except _asyncio.TimeoutError:
            _processing.discard(msg_id)
            await msg.edit_text("⏱ B-Stock scrape zaman aşımı (60s). Tekrar deneyin.")
            return

        t_scrape = round(time.time() - t0, 1)
        urun_sayisi = lot.product_count or len(lot.products)

        if urun_sayisi == 0:
            _processing.discard(msg_id)
            await msg.edit_text(
                "⚠️ Lot'ta ürün bulunamadı.\n\n"
                "B-Stock bu sayfayı görmek için giriş gerektirebilir.\n"
                "Çözüm: /credentials komutuyla email ve şifreni gir."
            )
            return

        await msg.edit_text(
            f"📦 {urun_sayisi} ürün bulundu (scrape: {t_scrape}s). eBay fiyatları araştırılıyor..."
        )

        try:
            result = await _asyncio.wait_for(_pipeline.run(lot), timeout=120.0)
        except _asyncio.TimeoutError:
            _processing.discard(msg_id)
            t_total = round(time.time() - t0, 1)
            await msg.edit_text(f"⏱ Pipeline timeout ({t_total}s). Scrape: {t_scrape}s. Tekrar gönderin.")
            return

        await Cache.push_history({
            "url": url,
            "lot_id": result.lot_id,
            "decision": result.overall_decision.value,
            "roi": result.best_roi,
            "max_bid": result.max_bid,
            "timestamp": int(time.time()),
        })

        messages = format_report(result)
        # Send messages FIRST, then delete progress msg
        for m in messages:
            await update.message.reply_text(m, parse_mode="Markdown")
        try:
            await msg.delete()
        except Exception:
            pass

    except Exception as e:
        import traceback
        tb = traceback.format_exc()[-600:]
        try:
            await msg.edit_text(f"❌ Hata: {str(e)[:300]}\n\n{tb}", parse_mode=None)
        except Exception:
            await update.message.reply_text(f"❌ Hata: {str(e)[:300]}\n\n{tb}")
    finally:
        _processing.discard(msg_id)


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return

    history = await Cache.get_history(10)
    if not history:
        await update.message.reply_text("📭 Henüz analiz geçmişi yok.")
        return

    import datetime
    lines = ["📋 *Son Analizler*\n"]
    for i, h in enumerate(history, 1):
        ts = datetime.datetime.fromtimestamp(h.get("timestamp", 0)).strftime("%m/%d %H:%M")
        lot_id = h.get("lot_id") or "?"
        decision = h.get("decision", "?")
        roi = h.get("roi", 0)
        max_bid = h.get("max_bid", 0)
        lines.append(f"{i}\\. `{lot_id}` — {decision} ROI:%{roi:.0f} MaxBid:${max_bid:.0f} \\({ts}\\)")

    await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")


async def cmd_credentials(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Usage: /credentials email@x.com şifre"""
    if not _is_allowed(update):
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Kullanım: `/credentials email@example.com şifren`",
            parse_mode="Markdown",
        )
        return
    email = context.args[0]
    password = context.args[1]
    # Store in Railway via env — for now save to config at runtime
    import config as cfg
    cfg.BSTOCK_EMAIL = email
    cfg.BSTOCK_PASSWORD = password
    await update.message.reply_text(
        f"✅ B-Stock girişi ayarlandı: `{email}`\n\n"
        "Şimdi linki tekrar gönder.",
        parse_mode="Markdown",
    )


async def cmd_debug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Usage: /debug <bstock_url>"""
    if not _is_allowed(update):
        return

    text = " ".join(context.args) if context.args else ""
    url_match = BSTOCK_URL_PATTERN.search(text)
    if not url_match:
        await update.message.reply_text("Kullanim: /debug <bstock_url>")
        return

    url = url_match.group(0)
    uid = extract_lot_id(url)
    email = getattr(config, "BSTOCK_EMAIL", "")

    msg = await update.message.reply_text("Debuglanıyor...")
    lines = ["=== DEBUG ===", f"UID: {uid}", f"Email: {email or 'YOK'}"]

    try:
        import json as _json

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:

            # Step 1: FusionAuth login with applicationId
            pwd = getattr(config, "BSTOCK_PASSWORD", "")
            fa_app_id = "1b094c5f-c8a6-416c-8c62-4dc77ca88ce9"
            auth_token = None
            if email and pwd:
                try:
                    r2 = await client.post(
                        "https://auth.bstock.com/api/login",
                        json={"loginId": email, "password": pwd, "applicationId": fa_app_id},
                        headers={**HEADERS, "Content-Type": "application/json"},
                        timeout=10.0,
                    )
                    lines.append(f"AUTH login: HTTP {r2.status_code} | {r2.text[:200]}")
                    if r2.status_code in (200, 201):
                        auth_token = r2.json().get("token")
                        lines.append(f"TOKEN: {str(auth_token)[:60]}")
                except Exception as e:
                    lines.append(f"AUTH hata: {str(e)[:100]}")

            # Step 2: Listing API with auth token
            if uid:
                listing_headers = {**HEADERS, "Accept": "application/json"}
                if auth_token:
                    listing_headers["Authorization"] = f"Bearer {auth_token}"
                try:
                    r3 = await client.get(
                        f"https://listing.bstock.com/v1/listings/{uid}",
                        headers=listing_headers, timeout=10.0
                    )
                    lines.append(f"LISTING: HTTP {r3.status_code}, {len(r3.text)} karakter")
                    if r3.status_code == 200:
                        listing_data = r3.json()
                        lot_id = listing_data.get("lotId")
                        lines.append(f"lotId: {lot_id}")
                        lines.append(f"status: {listing_data.get('status')}")
                        lines.append(f"docs: {[(d.get('docType'), d.get('url','')[-30:]) for d in listing_data.get('documents', [])]}")

                        pretty_id = listing_data.get("prettyId")
                        formatted_id = listing_data.get("formattedPrettyId")
                        storefront_id = listing_data.get("storefrontId")
                        lines.append(f"prettyId: {pretty_id}, formattedPrettyId: {formatted_id}")
                        lines.append(f"storefrontId: {storefront_id}")

                        # Offering API
                        try:
                            ro = await client.get(f"https://offering.bstock.com/v1/offerings?listingId={uid}", headers=listing_headers, timeout=8.0)
                            od = ro.json()
                            lines.append(f"Offerings: total={od.get('total')}, count={len(od.get('offerings',[]))}")
                            if od.get("offerings"):
                                lines.append(f"Offering[0] keys: {list(od['offerings'][0].keys())}")
                                lines.append(f"Offering[0]: {str(od['offerings'][0])[:300]}")
                        except Exception as e:
                            lines.append(f"Offering ERR: {e}")

                        # Show full shipping and saleMetrics
                        lines.append(f"shipping: {listing_data.get('shipping')}")
                        lines.append(f"saleMetrics: {listing_data.get('saleMetrics')}")

                        # Docserv: list ALL documents for this listing
                        try:
                            rd_all = await client.get(
                                f"https://docserv.bstock.com/v1/documents?listingId={uid}",
                                headers=listing_headers, timeout=8.0
                            )
                            lines.append(f"docserv ALL docs: HTTP {rd_all.status_code}")
                            if rd_all.status_code == 200:
                                dd = rd_all.json()
                                docs_list = dd.get("documents", [])
                                lines.append(f"  total docs: {len(docs_list)}")
                                for doc in docs_list:
                                    lines.append(f"  doc: {doc.get('filename')} | type={doc.get('contentType')} | docType={doc.get('docType')} | url={str(doc.get('url',''))[-50:]}")
                        except Exception as e:
                            lines.append(f"docserv ALL ERR: {e}")

                        # Auction API - full data
                        auction_id = None
                        try:
                            ra = await client.get(
                                f"https://auction.bstock.com/v1/auctions?listingId={uid}",
                                headers=listing_headers, timeout=8.0
                            )
                            lines.append(f"Auction: HTTP {ra.status_code}")
                            if ra.status_code == 200:
                                ad = ra.json()
                                auctions = ad.get("auctions", [])
                                lines.append(f"  count: {len(auctions)}")
                                if auctions:
                                    a0 = auctions[0]
                                    auction_id = a0.get("_id")
                                    lines.append(f"  auction _id: {auction_id}")
                                    lines.append(f"  winningBidAmount: {a0.get('winningBidAmount')} | startPrice: {a0.get('startPrice')} | nextMinBidAmount: {a0.get('nextMinBidAmount')}")
                                    lines.append(f"  keys: {list(a0.keys())}")
                                    # Show full attributes (untruncated) to find B-Stock Fee field
                                    attrs = a0.get("attributes") or {}
                                    lines.append(f"  attributes keys: {list(attrs.keys())}")
                                    lines.append(f"  attributes: {str(attrs)[:1500]}")
                        except Exception as e:
                            lines.append(f"Auction ERR: {e}")

                        # Auction sub-endpoints for manifest/items
                        if auction_id:
                            for sub in [
                                f"https://auction.bstock.com/v1/auctions/{auction_id}",
                                f"https://auction.bstock.com/v1/auctions/{auction_id}/items",
                                f"https://auction.bstock.com/v1/auctions/{auction_id}/manifest",
                                f"https://auction.bstock.com/v1/auctions/{auction_id}/lots",
                            ]:
                                try:
                                    rs = await client.get(sub, headers=listing_headers, timeout=7.0)
                                    lines.append(f"[{rs.status_code}] {sub.split('auctions')[1]} | {rs.text[:120]}")
                                    if rs.status_code == 200:
                                        break
                                except Exception as e:
                                    lines.append(f"ERR: {str(e)[:50]}")

                        # Manifest discovery: probe every known pattern
                        import re as _re
                        listing_lot_id = listing_data.get("lotId") or ""
                        lines.append(f"listing.lotId: {listing_lot_id}")

                        auction_title = ""
                        if auctions:
                            auction_title = (auctions[0].get("attributes") or {}).get("title", "") or auctions[0].get("title", "")
                            lines.append(f"auction title: {auction_title[:200]}")

                        nm = _re.search(r'[-\(](\d{5,8})\)?', auction_title)
                        numeric_id = nm.group(1) if nm else None
                        lines.append(f"numeric_lot_id from title: {numeric_id}")

                        probe_ids = list({uid, listing_lot_id, numeric_id} - {None, ""})
                        probe_bases = [
                            ("ingestion", "https://ingestion.bstock.com/v1"),
                            ("listing",   "https://listing.bstock.com/v1"),
                            ("auction",   "https://auction.bstock.com/v1"),
                        ]
                        probe_paths = [
                            "/lots/{id}/items",
                            "/lots/{id}",
                            "/manifests/{id}",
                            "/manifests/{id}/items",
                            "/listings/{id}/manifest",
                            "/listings/{id}/items",
                            "/listings/{id}/products",
                            "/auctions/{id}/items",
                            "/auctions/{id}/manifest",
                        ]
                        for base_name, base_url in probe_bases:
                            for pid in probe_ids:
                                for path_tpl in probe_paths:
                                    path = path_tpl.replace("{id}", pid)
                                    full = base_url + path
                                    try:
                                        rp = await client.get(full, headers=listing_headers, timeout=6.0)
                                        if rp.status_code == 200:
                                            lines.append(f"HIT [{rp.status_code}] {base_name}{path}: {rp.text[:300]}")
                                        # only log non-404 failures to keep output short
                                        elif rp.status_code not in (404, 403):
                                            lines.append(f"[{rp.status_code}] {base_name}{path}")
                                    except Exception as e:
                                        pass

                    else:
                        lines.append(r3.text[:200])
                except Exception as e:
                    lines.append(f"LISTING ERR: {str(e)[:100]}")

    except Exception as e:
        lines.append(f"GENEL HATA: {e}")

    report = "\n".join(lines)
    await msg.edit_text(report[:4000])


async def cmd_testebay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Usage: /testebay Apple Watch Ultra"""
    if not _is_allowed(update):
        return
    query = " ".join(context.args) if context.args else "Apple Watch Ultra"
    msg = await update.message.reply_text(f"eBay testi: '{query}' aranıyor...")
    lines = [f"Query: {query}"]

    import config as _cfg
    bd_key = getattr(_cfg, "BRIGHTDATA_API_KEY", "")
    bd_zone = getattr(_cfg, "BRIGHTDATA_ZONE", "web_unlocker1")
    ebay_app_id = getattr(_cfg, "EBAY_APP_ID", "")
    lines.append(f"BrightData key: {'SET' if bd_key else 'MISSING'}")
    lines.append(f"eBay App ID: {'SET' if ebay_app_id else 'MISSING'}")

    # Test 1a: findCompletedItems
    if ebay_app_id:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                params = {
                    "OPERATION-NAME": "findCompletedItems",
                    "SERVICE-VERSION": "1.0.0",
                    "SECURITY-APPNAME": ebay_app_id,
                    "RESPONSE-DATA-FORMAT": "JSON",
                    "keywords": query,
                    "itemFilter(0).name": "SoldItemsOnly",
                    "itemFilter(0).value": "true",
                    "paginationInput.entriesPerPage": "5",
                }
                r = await client.get("https://svcs.ebay.com/services/search/FindingService/v1", params=params)
                lines.append(f"findCompletedItems: HTTP {r.status_code} | {r.text[:300]}")
        except Exception as e:
            lines.append(f"findCompletedItems ERR: {e}")

    # Test 1b: findItemsByKeywords (basic search — less restricted)
    if ebay_app_id:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                params2 = {
                    "OPERATION-NAME": "findItemsByKeywords",
                    "SERVICE-VERSION": "1.0.0",
                    "SECURITY-APPNAME": ebay_app_id,
                    "RESPONSE-DATA-FORMAT": "JSON",
                    "keywords": query,
                    "paginationInput.entriesPerPage": "3",
                }
                r2 = await client.get("https://svcs.ebay.com/services/search/FindingService/v1", params=params2)
                lines.append(f"findItemsByKeywords: HTTP {r2.status_code} | {r2.text[:300]}")
        except Exception as e:
            lines.append(f"findItemsByKeywords ERR: {e}")

    # Test 1c: Browse API with OAuth
    if ebay_app_id:
        import base64 as _b64
        cert_id = "PRD-6c21b7a29737-ebe0-43a4-bd70-f269"
        try:
            creds = _b64.b64encode(f"{ebay_app_id}:{cert_id}".encode()).decode()
            async with httpx.AsyncClient(timeout=15.0) as client:
                tok_r = await client.post(
                    "https://api.ebay.com/identity/v1/oauth2/token",
                    headers={"Authorization": f"Basic {creds}", "Content-Type": "application/x-www-form-urlencoded"},
                    data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"},
                )
                lines.append(f"OAuth token: HTTP {tok_r.status_code}")
                if tok_r.status_code == 200:
                    token = tok_r.json().get("access_token", "")
                    # Browse API - active listings
                    browse_r = await client.get(
                        "https://api.ebay.com/buy/browse/v1/item_summary/search",
                        headers={"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"},
                        params={"q": query, "limit": "10", "filter": "buyingOptions:{FIXED_PRICE}"},
                    )
                    if browse_r.status_code == 200:
                        items = browse_r.json().get("itemSummaries", [])
                        prices = [float(i["price"]["value"]) for i in items if "price" in i]
                        lines.append(f"Browse API active: {len(items)} items, prices: {[round(p,2) for p in prices[:5]]}")
                    else:
                        lines.append(f"Browse API: HTTP {browse_r.status_code} | {browse_r.text[:200]}")
                    # Marketplace Insights - sold prices (beta)
                    ins_r = await client.get(
                        "https://api.ebay.com/buy/marketplace_insights/v1_beta/item_sales/search",
                        headers={"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"},
                        params={"q": query, "limit": "10"},
                    )
                    if ins_r.status_code == 200:
                        sales = ins_r.json().get("itemSales", [])
                        sold_prices = [float(s["lastSoldPrice"]["value"]) for s in sales if "lastSoldPrice" in s]
                        lines.append(f"Insights SOLD: {len(sales)} items, prices: {[round(p,2) for p in sold_prices[:5]]}")
                    else:
                        lines.append(f"Insights API: HTTP {ins_r.status_code} | {ins_r.text[:150]}")
        except Exception as e:
            lines.append(f"Browse/Insights ERR: {type(e).__name__}: {str(e)[:150]}")

    # Test 2: eBay direct (no proxy)
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            r = await client.get(
                "https://www.ebay.com/sch/i.html",
                params={"_nkw": query, "LH_Complete": "1", "LH_Sold": "1", "_ipg": "5"},
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"},
            )
            lines.append(f"eBay direct: HTTP {r.status_code}, {len(r.text)} chars")
            if r.status_code == 200:
                from bs4 import BeautifulSoup as _BS
                prices = [el.get_text(strip=True) for el in _BS(r.text, "lxml").select(".s-item__price")[:5]]
                lines.append(f"Prices found: {prices}")
    except Exception as e:
        lines.append(f"eBay direct ERR: {str(e)[:100]}")

    import urllib.parse as _up
    bd_url = "https://www.ebay.com/sch/i.html?" + _up.urlencode(
        {"_nkw": query, "LH_Complete": "1", "LH_Sold": "1", "_ipg": "60"}
    )
    import config as _cfg2
    _api_key = getattr(_cfg2, "BRIGHTDATA_API_KEY", "")
    _zone = getattr(_cfg2, "BRIGHTDATA_ZONE", "web_unlocker1")
    lines.append(f"BD key (last 8): ...{_api_key[-8:] if _api_key else 'EMPTY'}")

    # Test 3a: BrightData WITHOUT JS render
    try:
        async with httpx.AsyncClient(timeout=55.0) as _c:
            _r = await _c.post(
                "https://api.brightdata.com/request",
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {_api_key}"},
                json={"zone": _zone, "url": bd_url, "format": "raw"},
            )
            lines.append(f"BD no-render: HTTP {_r.status_code}, {len(_r.text)} chars")
            if _r.status_code == 200:
                from bs4 import BeautifulSoup as _BS2
                prices_a = [el.get_text(strip=True) for el in _BS2(_r.text, "lxml").select(".s-item__price")[:5]]
                lines.append(f"  .s-item__price: {prices_a}")
    except Exception as e:
        lines.append(f"BD no-render ERR: {type(e).__name__}: {repr(e)[:200]}")

    # Test 3b: BrightData WITH JS render (render must be bool)
    try:
        async with httpx.AsyncClient(timeout=90.0) as _c:
            _r2 = await _c.post(
                "https://api.brightdata.com/request",
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {_api_key}"},
                json={"zone": _zone, "url": bd_url, "format": "raw", "render": True},
            )
            lines.append(f"BD js-render: HTTP {_r2.status_code}, {len(_r2.text)} chars")
            if _r2.status_code == 200:
                from bs4 import BeautifulSoup as _BS3
                prices_b = [el.get_text(strip=True) for el in _BS3(_r2.text, "lxml").select(".s-item__price")[:5]]
                lines.append(f"  .s-item__price: {prices_b}")
            else:
                lines.append(f"  response: {_r2.text[:200]}")
    except Exception as e:
        lines.append(f"BD js-render ERR: {type(e).__name__}: {repr(e)[:200]}")

    await msg.edit_text("\n".join(lines)[:4000])


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update):
        return

    try:
        client = await Cache.get_client()
        await client.ping()
        redis_ok = "✅"
    except Exception:
        redis_ok = "❌"

    await update.message.reply_text(
        f"🤖 *Bot Durumu*\n\n"
        f"Redis: {redis_ok}\n"
        f"Bot: ✅ Aktif",
        parse_mode="Markdown",
    )
