from models.analysis import AnalysisResult, Decision, PlatformResult, ProductAnalysis
from typing import List


DECISION_EMOJI = {
    Decision.BUY: "✅",
    Decision.SKIP: "❌",
    Decision.RISKY: "⚠️",
}


def format_report(result: AnalysisResult) -> List[str]:
    parts = []
    parts.append(_header(result))
    parts.append(_platform_section(result))
    parts.append(_product_section(result.products[:10]))
    parts.append(_conclusion(result))

    # Split into <=4096-char messages for Telegram
    messages = []
    buffer = ""
    for part in parts:
        if len(buffer) + len(part) > 4000:
            messages.append(buffer)
            buffer = part
        else:
            buffer += "\n" + part if buffer else part
    if buffer:
        messages.append(buffer)
    return messages


def _header(r: AnalysisResult) -> str:
    premium = r.buyers_premium or 0
    premium_rate = (premium / r.current_bid * 100) if r.current_bid else 0
    return (
        "📊 *B\\-STOCK LOT ANALİZ RAPORU*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔗 Lot: {_esc(r.lot_url)}\n"
        f"📦 Toplam Ürün: {r.product_count}\n"
        f"💰 Mevcut Fiyat/Bid: ${r.current_bid or 0:,.2f}\n"
        f"🚚 Kargo: ${r.shipping_cost or 0:,.2f}\n"
        f"💳 Buyer's Premium: ${premium:,.2f} \\(%{premium_rate:.0f}\\)\n"
        f"📋 Toplam Maliyet: ${r.total_cost or 0:,.2f}\n"
    )


def _platform_section(r: AnalysisResult) -> str:
    if not r.platform_totals:
        return ""

    total_values = {
        "eBay Used Ort\\.": r.platform_totals.get("eBay"),
        "Amazon Used Ort\\.": r.platform_totals.get("Amazon"),
        "FB/Flea Market Ort\\.": r.platform_totals.get("Facebook/Flea"),
    }

    revenues = [v.estimated_revenue for v in r.platform_totals.values() if v]
    overall_avg = sum(revenues) / len(revenues) if revenues else 0

    lines = [
        "\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n📈 *GENEL ÖZET*\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n",
        f"Toplam Tahmini Değer: ${overall_avg:,.0f}",
    ]
    for label, pt in total_values.items():
        if pt:
            lines.append(f"  ├─ {label}: ${pt.estimated_revenue:,.0f}")
    lines.append(f"\n💡 Max Bid Önerisi: *${r.max_bid:,.0f}*\n")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n🏪 *PLATFORM BAZLI ANALİZ*\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    platform_emoji = {"eBay": "📱", "Shopify": "🛒", "Amazon": "📦", "Facebook/Flea": "🏪"}
    for name, pt in r.platform_totals.items():
        emoji = platform_emoji.get(name, "🔹")
        dec = DECISION_EMOJI.get(pt.decision, "")
        risk_label = f" \\({pt.risk_level.value}\\)" if pt.risk_level else ""
        lines.append(
            f"{emoji} *{_esc(name)}*:\n"
            f"  ├─ Tahmini Gelir: ${pt.estimated_revenue:,.0f}\n"
            f"  ├─ Fee: \\-${pt.fees:,.0f}\n"
            f"  ├─ Kargo: \\-${pt.shipping_out:,.0f}\n"
            f"  ├─ Net Kâr: ${pt.net_profit:,.0f}\n"
            f"  ├─ ROI: %{pt.roi:.1f}\n"
            f"  └─ Karar: {dec} {_esc(pt.decision.value)}{risk_label}\n"
        )

    return "\n".join(lines)


def _product_section(products: List[ProductAnalysis]) -> str:
    if not products:
        return ""
    lines = ["\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n📋 *ÜRÜN DETAYLARI \\(Top 10\\)*\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n"]
    numbers = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

    for i, pa in enumerate(products):
        num = numbers[i] if i < len(numbers) else f"{i+1}\\."
        fake_flag = " ⚠️" if pa.fake_msrp else ""
        real_msrp_str = f"${pa.real_msrp:,.0f}" if pa.real_msrp else "N/A"
        ebay_str = f"${pa.ebay_sold_avg:,.0f}" if pa.ebay_sold_avg else "N/A"
        amz_str = f"${pa.amazon_used:,.0f}" if pa.amazon_used else "N/A"
        st_str = f"%{pa.sell_through_rate*100:.0f}" if pa.sell_through_rate else "N/A"
        trend_str = pa.price_trend or "N/A"
        days_str = f"~{pa.estimated_days_to_sell} gün" if pa.estimated_days_to_sell else "N/A"

        lines.append(
            f"{num} *{_esc(pa.name)}*\n"
            f"   Condition: {_esc(pa.condition)} \\| Adet: {pa.quantity}\n"
            f"   B\\-Stock MSRP: ${pa.listed_msrp:,.0f}" + (f" \\| Gerçek MSRP: {real_msrp_str}{fake_flag}" if pa.real_msrp else "") + "\n"
            f"   eBay Sold Avg: {ebay_str} \\| Amazon Used: {amz_str}\n"
            f"   Sell\\-through: {st_str} \\| Trend: {_esc(trend_str)}\n"
            f"   Tahmini Satış Süresi: {days_str}\n"
        )

    return "\n".join(lines)


def _conclusion(r: AnalysisResult) -> str:
    dec = DECISION_EMOJI.get(r.overall_decision, "")
    best = _esc(r.best_platform or "N/A")
    days_str = f"~{r.estimated_capital_return_days} gün" if r.estimated_capital_return_days else "N/A"
    return (
        "\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n🏆 *SONUÇ*\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"En İyi Platform: {best}\n"
        f"En İyi ROI: %{r.best_roi:.1f}\n"
        f"Genel Tavsiye: {dec} *{_esc(r.overall_decision.value)}*\n"
        f"Tahmini Sermaye Dönüş Süresi: {days_str}\n"
        f"Max Bid: *${r.max_bid:,.0f}*\n"
        f"\n⏱ Analiz süresi: {r.analysis_duration_seconds:.1f}sn"
    )


def _esc(text: str) -> str:
    special = r"\_*[]()~`>#+-=|{}.!"
    for ch in special:
        text = text.replace(ch, f"\\{ch}")
    return text
