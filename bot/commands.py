import re
from telegram import Update
from telegram.ext import ContextTypes
import config
from scraper.bstock import BStockScraper
from analyzer.pipeline import AnalysisPipeline
from bot.formatter import format_report
from utils.cache import Cache


BSTOCK_URL_PATTERN = re.compile(r"https?://[^\s]*b-?stock[^\s]*", re.IGNORECASE)

_scraper = BStockScraper()
_pipeline = AnalysisPipeline()

# Simple rate limiter per user
_rate_tracker: dict[int, list] = {}
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
    if not _check_rate_limit(user_id):
        await update.message.reply_text("⏳ Çok hızlı! Dakikada en fazla 5 analiz yapılabilir.")
        return

    msg = await update.message.reply_text("🔍 Lot scrape ediliyor...")

    try:
        lot = await _scraper.scrape_lot(url)

        urun_sayisi = lot.product_count or len(lot.products)
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
        tb = traceback.format_exc()[-500:]
        await msg.edit_text(f"❌ Hata: {str(e)[:300]}\n\n```{tb}```", parse_mode="Markdown")


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
