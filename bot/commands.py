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
        lot = await _scraper.scrape_lot(url)

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
            f"📦 {urun_sayisi} ürün bulundu. Pazar fiyatları araştırılıyor... (~60-90 sn)"
        )

        result = await _pipeline.run(lot)

        await Cache.push_history({
            "url": url,
            "lot_id": result.lot_id,
            "decision": result.overall_decision.value,
            "roi": result.best_roi,
            "max_bid": result.max_bid,
            "timestamp": int(time.time()),
        })

        messages = format_report(result)
        await msg.delete()
        for m in messages:
            await update.message.reply_text(m, parse_mode="MarkdownV2")

    except Exception as e:
        import traceback
        tb = traceback.format_exc()[-400:]
        await msg.edit_text(f"❌ Hata: {str(e)[:200]}\n\n`{tb}`", parse_mode="Markdown")
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
    """Usage: /debug <bstock_url>  — diagnose why scraping fails"""
    if not _is_allowed(update):
        return

    text = " ".join(context.args) if context.args else ""
    url_match = BSTOCK_URL_PATTERN.search(text)
    if not url_match:
        await update.message.reply_text("Kullanım: `/debug <bstock_url>`", parse_mode="Markdown")
        return

    url = url_match.group(0)
    uid = extract_lot_id(url)
    email = getattr(config, "BSTOCK_EMAIL", "")
    password = getattr(config, "BSTOCK_PASSWORD", "")

    msg = await update.message.reply_text("🔬 Debug başlıyor...")
    lines = [f"🔬 *Debug Raporu*", f"URL: `{url[-40:]}`", f"UID: `{uid}`", f"Email: `{email or 'YOK'}`", ""]

    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            # Step 1: Homepage
            try:
                r = await client.get(BSTOCK_HOME, headers=HEADERS)
                lines.append(f"1\\. Homepage: HTTP {r.status_code}, {len(r.text)} karakter")
            except Exception as e:
                lines.append(f"1\\. Homepage: HATA {e}")

            # Step 2: Login
            login_ok = False
            if email and password:
                try:
                    r = await client.post(
                        LOGIN_URL,
                        json={"email": email, "password": password},
                        headers={**HEADERS, "Content-Type": "application/json"},
                    )
                    body_preview = r.text[:200].replace("`", "'")
                    lines.append(f"2\\. Login API: HTTP {r.status_code}")
                    lines.append(f"   Yanıt: `{body_preview}`")
                    login_ok = r.status_code in (200, 201, 302)
                except Exception as e:
                    lines.append(f"2\\. Login: HATA {e}")
            else:
                lines.append("2\\. Login: email/şifre girilmemiş")

            # Step 3: Fetch lot page
            try:
                r = await client.get(url, headers=HEADERS)
                has_next_data = "__NEXT_DATA__" in r.text
                has_products = any(k in r.text for k in ["manifest", "products", "items", "\"name\""])
                lines.append(f"3\\. Lot sayfası: HTTP {r.status_code}, {len(r.text)} karakter")
                lines.append(f"   \\_\\_NEXT\\_DATA\\_\\_: {'✅' if has_next_data else '❌'}")
                lines.append(f"   Ürün verisi işareti: {'✅' if has_products else '❌'}")
            except Exception as e:
                lines.append(f"3\\. Lot sayfası: HATA {e}")

            # Step 4: Show __NEXT_DATA__ key structure
            from scraper.bstock import BStockScraper as _BS
            lot_html = None
            try:
                r4 = await client.get(url, headers=HEADERS)
                lot_html = r4.text
            except Exception:
                pass
            if lot_html:
                nd = _BS._extract_next_data(lot_html)
                if nd:
                    try:
                        import json as _json
                        nd_obj = _json.loads(nd)
                        def _keys(d, depth=0):
                            if depth > 3 or not isinstance(d, dict):
                                return []
                            out = []
                            for k, v in list(d.items())[:15]:
                                vtype = type(v).__name__
                                vlen = f"[{len(v)}]" if isinstance(v, (list, dict)) else ""
                                out.append("  " * depth + f"`{k}` {vtype}{vlen}")
                                out.extend(_keys(v, depth + 1))
                            return out
                        key_lines = _keys(nd_obj)[:40]
                        lines.append(f"4\\. \\_\\_NEXT\\_DATA\\_\\_ keys \\({len(nd)} karakter\\):")
                        lines.extend(key_lines)
                    except Exception as ex:
                        lines.append(f"4\\. \\_\\_NEXT\\_DATA\\_\\_ parse hata: {ex}")
                else:
                    lines.append("4\\. \\_\\_NEXT\\_DATA\\_\\_ bulunamadı")

    except Exception as e:
        lines.append(f"❌ Genel hata: {e}")

    report = "\n".join(lines)
    await msg.edit_text(report[:4000], parse_mode="MarkdownV2")


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
