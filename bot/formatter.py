from models.analysis import AnalysisResult, Decision, PlatformResult, ProductAnalysis
from typing import List, Optional


DECISION_EMOJI = {
    Decision.BUY: "✅",
    Decision.SKIP: "❌",
    Decision.RISKY: "⚠️",
}


def _n(val: Optional[float], fmt: str = ",.0f", fallback: str = "N/A") -> str:
    if val is None:
        return fallback
    return format(val, fmt)


def _esc(text: Optional[str]) -> str:
    if not text:
        return "N/A"
    # Markdown v1: only escape *, _, `, [
    for ch in ["*", "_", "`", "["]:
        text = text.replace(ch, f"\\{ch}")
    return text


def format_report(result: AnalysisResult) -> List[str]:
    parts = [
        _header(result),
        _platform_section(result),
        _product_section(result.products[:10]),
        _conclusion(result),
    ]

    messages = []
    buffer = ""
    for part in parts:
        if not part:
            continue
        if len(buffer) + len(part) > 3800:
            if buffer:
                messages.append(buffer)
            buffer = part
        else:
            buffer += ("\n" + part) if buffer else part
    if buffer:
        messages.append(buffer)
    return messages or ["Analiz tamamlandı ancak rapor oluşturulamadı."]


def _header(r: AnalysisResult) -> str:
    premium = r.buyers_premium or 0
    premium_rate = (premium / r.current_bid * 100) if r.current_bid else 0
    return (
        "📊 *B-STOCK LOT ANALİZ RAPORU*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 Toplam Ürün: {r.product_count}\n"
        f"💰 Mevcut Bid: ${_n(r.current_bid)}\n"
        f"🚚 Kargo: ${_n(r.shipping_cost)}\n"
        f"💳 Buyer's Premium: ${_n(premium)} (%{premium_rate:.0f})\n"
        f"📋 Toplam Maliyet: ${_n(r.total_cost)}\n"
    )


def _platform_section(r: AnalysisResult) -> str:
    if not r.platform_totals:
        return "⚠️ Fiyat verisi bulunamadı — eBay sorguları sonuç döndürmedi.\n"

    revenues = [v.estimated_revenue for v in r.platform_totals.values() if v]
    overall_avg = sum(revenues) / len(revenues) if revenues else 0

    lines = [
        "\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n📈 *GENEL ÖZET*\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n",
        f"Toplam Tahmini Değer: ${overall_avg:,.0f}",
        f"💡 *Max Bid Önerisi: ${r.max_bid:,.0f}*\n",
        "\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n🏪 *PLATFORM BAZLI ANALİZ*\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n",
    ]

    platform_emoji = {"eBay": "📱", "Shopify": "🛒", "Amazon": "📦", "Facebook/Flea": "🏪"}
    for name, pt in r.platform_totals.items():
        emoji = platform_emoji.get(name, "🔹")
        dec = DECISION_EMOJI.get(pt.decision, "")
        risk_label = f" ({pt.risk_level.value})" if pt.risk_level else ""
        lines.append(
            f"{emoji} *{_esc(name)}*:\n"
            f"  Tahmini Gelir: ${pt.estimated_revenue:,.0f}\n"
            f"  Fee: -${pt.fees:,.0f} | Kargo: -${pt.shipping_out:,.0f}\n"
            f"  Net Kar: ${pt.net_profit:,.0f} | ROI: %{pt.roi:.1f}\n"
            f"  Karar: {dec} {_esc(pt.decision.value)}{risk_label}\n"
        )

    return "\n".join(lines)


def _product_section(products: List[ProductAnalysis]) -> str:
    if not products:
        return ""
    lines = ["\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n📋 *ÜRÜN DETAYLARI*\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n"]

    for i, pa in enumerate(products, 1):
        msrp_str = f"${_n(pa.listed_msrp)}"
        ebay_str = f"${_n(pa.ebay_sold_avg)}"
        amz_str = f"${_n(pa.amazon_used)}"

        lines.append(
            f"{i}. *{_esc(pa.name)}*\n"
            f"   Durum: {_esc(pa.condition)} | Adet: {pa.quantity}\n"
            f"   MSRP: {msrp_str} | eBay Ort: {ebay_str} | Amazon: {amz_str}\n"
        )

    return "\n".join(lines)


def _conclusion(r: AnalysisResult) -> str:
    dec = DECISION_EMOJI.get(r.overall_decision, "")
    best = r.best_platform or "N/A"
    best_roi = max(r.best_roi, 0.0)
    return (
        "\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n🏆 *SONUÇ*\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"En İyi Platform: {_esc(best)}\n"
        f"En İyi ROI: %{best_roi:.1f}\n"
        f"Genel Tavsiye: {dec} *{_esc(r.overall_decision.value)}*\n"
        f"Max Bid: *${r.max_bid:,.0f}*\n"
        f"\n⏱ Analiz süresi: {r.analysis_duration_seconds:.1f}sn"
    )
