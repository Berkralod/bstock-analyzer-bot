import asyncio
from models.analysis import ProductAnalysis
from scraper.ebay import EbayScraper


SEASONAL_KEYWORDS = {
    "christmas", "holiday", "halloween", "summer", "winter", "pool",
    "fan", "heater", "snow", "leaf blower",
}


class Layer3Deep:
    """Deep analysis for high-potential products (ROI > 50%)."""

    def __init__(self) -> None:
        self._ebay = EbayScraper()

    async def analyze_all(self, products: list[ProductAnalysis]) -> None:
        await asyncio.gather(*[self._analyze(p) for p in products])

    async def _analyze(self, pa: ProductAnalysis) -> None:
        active_count = await self._ebay.get_active_count(pa.name)
        pa.competition_count = active_count

        sold_count = 0
        if pa.ebay_sold_avg is not None:
            sold_count = 20

        total = active_count + sold_count
        if total > 0:
            pa.sell_through_rate = round(sold_count / total, 2)
        else:
            pa.sell_through_rate = 0.5

        pa.estimated_days_to_sell = self._estimate_days(pa.sell_through_rate, active_count)
        pa.price_trend = self._estimate_trend(pa.ebay_sold_min, pa.ebay_sold_avg, pa.ebay_sold_max)
        pa.seasonality_flag = self._check_seasonality(pa.name)

    def _estimate_days(self, sell_through: float, competition: int) -> int:
        if sell_through >= 0.80:
            return 7
        if sell_through >= 0.60:
            return 14
        if sell_through >= 0.40:
            return 30
        return 60

    def _estimate_trend(
        self,
        price_min: float | None,
        price_avg: float | None,
        price_max: float | None,
    ) -> str:
        if price_min is None or price_avg is None or price_max is None:
            return "Stable"
        spread = price_max - price_min
        if price_avg and spread > price_avg * 0.30:
            return "↗️ Rising"
        if price_avg and spread < price_avg * 0.10:
            return "➡️ Stable"
        return "↘️ Falling"

    def _check_seasonality(self, name: str) -> bool:
        name_lower = name.lower()
        return any(kw in name_lower for kw in SEASONAL_KEYWORDS)
