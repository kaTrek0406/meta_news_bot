# -*- coding: utf-8 -*-
from typing import Optional
import os, httpx

DEFAULT_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "25"))
HEADERS = {
    "User-Agent": "MetaNewsWatcher/1.0 (+telegram bot)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

async def fetch_text(url: str, timeout: Optional[float] = None) -> str:
    t = timeout or DEFAULT_TIMEOUT
    async with httpx.AsyncClient(timeout=t, headers=HEADERS, follow_redirects=True) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.text
