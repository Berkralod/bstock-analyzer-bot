import json
from typing import List, Dict, Any
import anthropic
import config


class HaikuClient:
    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(
            api_key=config.ANTHROPIC_API_KEY,
            timeout=30.0,  # default is 600s — way too long
        )

    async def normalize_product_names(self, names: List[str]) -> List[Dict[str, Any]]:
        prompt = (
            "You are a product research assistant. For each product name below, "
            "return a JSON array where each element has:\n"
            '- "original": the original name\n'
            '- "normalized": clean search-ready name (brand + model, no extra words)\n'
            '- "brand": brand name if detectable\n'
            '- "model": model number if detectable\n'
            '- "category": product category (e.g. "Power Tools", "Electronics")\n\n'
            "Products:\n"
            + "\n".join(f"{i+1}. {n}" for i, n in enumerate(names))
            + "\n\nReturn ONLY valid JSON array, no markdown."
        )
        message = await self._client.messages.create(
            model=config.HAIKU_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(text)

    async def estimate_fb_price(self, product_name: str, ebay_avg: float, condition: str) -> float:
        prompt = (
            f"Product: {product_name}\nCondition: {condition}\neBay avg sold: ${ebay_avg:.2f}\n\n"
            "Estimate a reasonable Facebook Marketplace / flea market selling price in USD. "
            "FB/flea market prices are typically 10-30% higher than eBay used prices for most items "
            "because there are no fees, but can vary by category. "
            "Return ONLY a number (no $, no text)."
        )
        message = await self._client.messages.create(
            model=config.HAIKU_MODEL,
            max_tokens=32,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip().replace("$", "").replace(",", "")
        return float(raw)

    async def parse_bstock_html(self, html_chunk: str) -> Dict[str, Any]:
        prompt = (
            "Extract lot data from this B-Stock page HTML. Return JSON with:\n"
            '- "title": lot title\n'
            '- "current_bid": number or null\n'
            '- "shipping_cost": number or null\n'
            '- "buyers_premium_rate": decimal (e.g. 0.15) or null\n'
            '- "products": array of {name, condition, quantity, msrp}\n'
            '- "manifest_url": string or null\n\n'
            f"HTML:\n{html_chunk[:8000]}\n\nReturn ONLY valid JSON."
        )
        message = await self._client.messages.create(
            model=config.HAIKU_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(text)

    async def parse_bstock_next_data(self, next_data_json: str) -> Dict[str, Any]:
        """Parse B-Stock __NEXT_DATA__ JSON to extract lot and product info."""
        prompt = (
            "This is the __NEXT_DATA__ JSON from a B-Stock lot page (Next.js app). "
            "Extract lot data and return JSON with:\n"
            '- "title": lot title string\n'
            '- "current_bid": number or null\n'
            '- "shipping_cost": number or null\n'
            '- "buyers_premium_rate": decimal (e.g. 0.15) or null\n'
            '- "products": array of {name, condition, quantity, msrp} — find ALL items/products/manifest entries\n'
            '- "manifest_url": CSV or PDF download URL or null\n\n'
            f"__NEXT_DATA__:\n{next_data_json[:40000]}\n\nReturn ONLY valid JSON, no markdown."
        )
        message = await self._client.messages.create(
            model=config.HAIKU_MODEL,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(text)
