import httpx
import config

_BRIGHTDATA_API = "https://api.brightdata.com/request"


async def fetch_via_brightdata(url: str, headers: dict | None = None) -> str | None:
    """Fetch any URL through BrightData Web Unlocker Direct API."""
    api_key = getattr(config, "BRIGHTDATA_API_KEY", "")
    zone = getattr(config, "BRIGHTDATA_ZONE", "web_unlocker1")
    if not api_key:
        return None
    try:
        payload: dict = {"zone": zone, "url": url, "format": "raw"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                _BRIGHTDATA_API,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                json=payload,
            )
            if resp.status_code == 200 and len(resp.text) > 500:
                return resp.text
    except Exception:
        pass
    return None


def brightdata_proxies() -> dict | None:
    """Legacy proxy-based access — kept for bstock.py fallback."""
    username = getattr(config, "BRIGHTDATA_USERNAME", "")
    password = getattr(config, "BRIGHTDATA_PASSWORD", "")
    if username and password:
        url = f"http://{username}:{password}@brd.superproxy.io:22225"
        return {"http://": url, "https://": url}
    return None
