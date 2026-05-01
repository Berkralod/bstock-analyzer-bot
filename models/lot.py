from pydantic import BaseModel
from typing import List, Optional
from .product import Product


class Lot(BaseModel):
    url: str
    lot_id: Optional[str] = None
    title: Optional[str] = None
    current_bid: Optional[float] = None
    shipping_cost: Optional[float] = None
    buyers_premium_rate: float = 0.15
    buyers_premium_amount: Optional[float] = None
    total_cost: Optional[float] = None
    product_count: int = 0
    products: List[Product] = []
    manifest_url: Optional[str] = None
    auction_end: Optional[str] = None
    seller: Optional[str] = None
    location: Optional[str] = None

    def compute_totals(self) -> None:
        if self.current_bid is not None:
            self.buyers_premium_amount = self.current_bid * self.buyers_premium_rate
            shipping = self.shipping_cost or 0.0
            self.total_cost = self.current_bid + self.buyers_premium_amount + shipping
        self.product_count = sum(p.quantity for p in self.products)
