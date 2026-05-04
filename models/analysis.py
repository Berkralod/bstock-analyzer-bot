from pydantic import BaseModel
from typing import List, Optional, Dict
from enum import Enum


class Decision(str, Enum):
    BUY = "AL"
    SKIP = "ALMA"
    RISKY = "RISKY"


class RiskLevel(str, Enum):
    LOW = "düşük risk"
    MEDIUM = "orta risk"
    HIGH_RISKY = "az riskli"
    MEDIUM_RISKY = "orta riskli"
    VERY_RISKY = "çok riskli"


class PlatformResult(BaseModel):
    platform: str
    estimated_revenue: float = 0.0
    fees: float = 0.0
    shipping_out: float = 0.0
    packaging: float = 0.0
    other_costs: float = 0.0
    net_profit: float = 0.0
    roi: float = 0.0
    decision: Decision = Decision.SKIP
    risk_level: Optional[RiskLevel] = None


class ProductAnalysis(BaseModel):
    name: str
    condition: str
    quantity: int
    listed_msrp: Optional[float] = None
    real_msrp: Optional[float] = None
    fake_msrp: bool = False
    ebay_sold_avg: Optional[float] = None
    ebay_sold_median: Optional[float] = None
    ebay_sold_min: Optional[float] = None
    ebay_sold_max: Optional[float] = None
    sell_through_rate: Optional[float] = None
    competition_count: Optional[int] = None
    price_trend: Optional[str] = None
    seasonality_flag: bool = False
    estimated_days_to_sell: Optional[int] = None
    cost_per_unit: float = 0.0
    platform_results: List[PlatformResult] = []


class AnalysisResult(BaseModel):
    lot_url: str
    lot_id: Optional[str] = None
    current_bid: Optional[float] = None
    shipping_cost: Optional[float] = None
    buyers_premium: Optional[float] = None
    total_cost: Optional[float] = None
    product_count: int = 0
    products: List[ProductAnalysis] = []
    platform_totals: Dict[str, PlatformResult] = {}
    best_platform: Optional[str] = None
    best_roi: float = 0.0
    overall_decision: Decision = Decision.SKIP
    max_bid: float = 0.0
    estimated_capital_return_days: Optional[int] = None
    analysis_duration_seconds: float = 0.0
    error: Optional[str] = None
