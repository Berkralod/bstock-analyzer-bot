from typing import Optional
from utils.haiku import HaikuClient


class FacebookMPEstimator:
    """
    Facebook Marketplace doesn't have a public API.
    We use Haiku to estimate prices based on eBay data and product category.
    """

    def __init__(self) -> None:
        self._haiku = HaikuClient()

    async def estimate_price(
        self,
        product_name: str,
        condition: str,
        ebay_avg: Optional[float],
    ) -> Optional[float]:
        if ebay_avg is None:
            return None
        try:
            return await self._haiku.estimate_fb_price(product_name, ebay_avg, condition)
        except Exception:
            # Fallback: FB is typically 15-20% above eBay used
            return round(ebay_avg * 1.18, 2)
