from models.analysis import AnalysisResult, Decision, ProductAnalysis
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
    for ch in ["*", "_", "`", "["]:
        text = text.replace(ch, f"\\{ch}")
    return text


def format_report(result: AnalysisResult) -> List[str]:
    parts = [
        _header(result),
        _ebay_section(result),
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
    premium_line = ""
    if premium > 0:
        premium_rate = (premium / r.current_bid * 100) if r.current_bid else 0
        premium_line = f"💳 Buyer's Premium: ${_n(premium)} (%{premium_rate:.0f})\n"
    return (
        "📊 *B-STOCK LOT ANALİZ RAPORU*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 Toplam Ürün: {r.product_count}\n"
        f"💰 Mevcut Bid: ${_n(r.current_bid)}\n"
        f"🚚 Kargo: ${_n(r.shipping_cost)}\n"
        f"{premium_line}"
        f"📋 Toplam Maliyet: ${_n(r.total_cost)}\n"
    )


def _ebay_section(r: AnalysisResult) -> str:
    ebay = r.platform_totals.get("eBay")
    if not ebay:
        return "⚠️ eBay fiyat verisi bulunamadı — sorgular sonuç döndürmedi.\n"

    dec = DECISION_EMOJI.get(ebay.decision, "")
    risk_label = f" ({ebay.risk_level.value})" if ebay.risk_level else ""
    return (
        "\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n📈 *EBAY ANALİZİ*\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Tahmini Gelir: ${ebay.estimated_revenue:,.0f}\n"
        f"Fee: -${ebay.fees:,.0f} | Kargo: -${ebay.shipping_out:,.0f}\n"
        f"Net Kar: ${ebay.net_profit:,.0f} | ROI: %{ebay.roi:.1f}\n"
        f"Karar: {dec} *{_esc(ebay.decision.value)}*{risk_label}\n"
        f"💡 *Max Bid Önerisi: ${r.max_bid:,.0f}*\n"
    )


def _product_section(products: List[ProductAnalysis]) -> str:
    if not products:
        return ""
    lines = ["\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n📋 *ÜRÜN DETAYLARI*\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n"]

    for i, pa in enumerate(products, 1):
        msrp_str = f"${_n(pa.listed_msrp)}"
        ebay_str = f"${_n(pa.ebay_sold_avg)}" if pa.ebay_sold_avg else "N/A"
        lines.append(
            f"{i}. *{_esc(pa.name)}*\n"
            f"   Durum: {_esc(pa.condition)} | Adet: {pa.quantity}\n"
            f"   MSRP: {msrp_str} | eBay Ort: {ebay_str}\n"
        )

    return "\n".join(lines)


def _conclusion(r: AnalysisResult) -> str:
    dec = DECISION_EMOJI.get(r.overall_decision, "")
    return (
        "\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n🏆 *SONUÇ*\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Genel Tavsiye: {dec} *{_esc(r.overall_decision.value)}*\n"
        f"Max Bid: *${r.max_bid:,.0f}*\n"
        f"\n⏱ Analiz süresi: {r.analysis_duration_seconds:.1f}sn"
    )
