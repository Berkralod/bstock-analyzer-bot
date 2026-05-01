import os
from typing import Set


# Telegram
TELEGRAM_BOT_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_WEBHOOK_SECRET: str = os.environ["TELEGRAM_WEBHOOK_SECRET"]
ALLOWED_USERS: Set[int] = {
    int(uid.strip())
    for uid in os.getenv("ALLOWED_USERS", "").split(",")
    if uid.strip()
}

# Bright Data
BRIGHTDATA_API_KEY: str = os.environ["BRIGHTDATA_API_KEY"]
BRIGHTDATA_ZONE: str = os.getenv("BRIGHTDATA_ZONE", "web_unlocker1")
BRIGHTDATA_PROXY_URL: str = (
    f"http://brd-customer-hl_{os.getenv('BRIGHTDATA_CUSTOMER_ID', '')}:"
    f"{BRIGHTDATA_API_KEY}@brd.superproxy.io:22225"
)

# Apify
APIFY_API_TOKEN: str = os.environ["APIFY_API_TOKEN"]
APIFY_EBAY_ACTOR: str = "dtrungtin/ebay-items-scraper"

# Anthropic / Claude Haiku
ANTHROPIC_API_KEY: str = os.environ["ANTHROPIC_API_KEY"]
HAIKU_MODEL: str = "claude-haiku-4-5-20251001"

# Redis
REDIS_URL: str = os.environ["REDIS_URL"]

# App
PORT: int = int(os.getenv("PORT", "8000"))
ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

# Cache TTLs (seconds)
CACHE_TTL_EBAY: int = 6 * 3600
CACHE_TTL_AMAZON: int = 2 * 3600
CACHE_TTL_GOOGLE: int = 4 * 3600
CACHE_TTL_LOT: int = 1 * 3600

# Rate limiting
MAX_ANALYSES_PER_MINUTE: int = 5

# Analysis thresholds
ROI_LAYER3_THRESHOLD: float = 50.0

# Platform fees
EBAY_FEE_RATE: float = 0.13
SHOPIFY_FEE_RATE: float = 0.029
SHOPIFY_FEE_FIXED: float = 0.30
AMAZON_REFERRAL_RATE: float = 0.15
AMAZON_FBA_FEE: float = 3.0
PACKAGING_COST_PER_ITEM: float = 3.0
FLEA_MARKET_TABLE_DAILY: float = 35.0

# Max bid target margin
MAX_BID_REVENUE_FRACTION: float = 0.45
