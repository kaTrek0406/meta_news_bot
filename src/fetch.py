# -*- coding: utf-8 -*-
from typing import Optional
import os, httpx

DEFAULT_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "25"))

# Настройки прокси из переменных окружения
PROXY_HOST = os.getenv("PROXY_HOST", "")  # например: brd.superproxy.io:33335
PROXY_USER = os.getenv("PROXY_USER", "")  # например: brd-customer-hl_3967120c-zone-residential_proxy1
PROXY_PASSWORD = os.getenv("PROXY_PASSWORD", "")  # например: viw0l29v3tb2

# Используем заголовки обычного браузера, чтобы не быть заблокированным Facebook/Meta
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

async def fetch_text(url: str, timeout: Optional[float] = None) -> str:
    t = timeout or DEFAULT_TIMEOUT
    
    # Настройка прокси, если указаны переменные окружения
    proxies = None
    if PROXY_HOST and PROXY_USER and PROXY_PASSWORD:
        proxy_url = f"http://{PROXY_USER}:{PROXY_PASSWORD}@{PROXY_HOST}"
        proxies = {"http://": proxy_url, "https://": proxy_url}
    
    async with httpx.AsyncClient(
        timeout=t,
        headers=HEADERS,
        follow_redirects=True,
        proxies=proxies
    ) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.text
