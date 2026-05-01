import config


def brightdata_proxies() -> dict | None:
    """
    Build BrightData proxy dict for httpx.
    Priority:
      1. BRIGHTDATA_USERNAME + BRIGHTDATA_PASSWORD (correct format from dashboard)
      2. Legacy BRIGHTDATA_API_KEY + BRIGHTDATA_ZONE (old single-key format)
    """
    username = getattr(config, "BRIGHTDATA_USERNAME", "")
    password = getattr(config, "BRIGHTDATA_PASSWORD", "")

    if username and password:
        url = f"http://{username}:{password}@brd.superproxy.io:22225"
        return {"http://": url, "https://": url}

    # Legacy fallback
    key = getattr(config, "BRIGHTDATA_API_KEY", "")
    zone = getattr(config, "BRIGHTDATA_ZONE", "web_unlocker1")
    if key and zone:
        url = f"http://zone-{zone}:{key}@brd.superproxy.io:22225"
        return {"http://": url, "https://": url}

    return None
