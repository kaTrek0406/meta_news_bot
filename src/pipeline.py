# -*- coding: utf-8 -*-
import logging
import os
import json
import time
import random
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Any, Optional

import asyncio
import httpx
from difflib import SequenceMatcher
import re

# Импорт curl-cffi для обхода TLS fingerprinting
try:
    from curl_cffi.requests import AsyncSession
    CURL_CFFI_AVAILABLE = True
except ImportError:
    CURL_CFFI_AVAILABLE = False
    AsyncSession = None

from .storage import load_cache, save_cache, compute_hash, get_cache_stats
from .config import (
    PROJECT_ROOT, SOURCES, USE_PROXY, PROXY_URL, PROXY_URL_EU,
    PROXY_PROVIDER, PROXY_STICKY, PROXY_FALLBACK_EU,
    SOCKS5_URL, SOCKS5_URL_EU, HTTP_TUNNEL_URL
)
from .html_clean import clean_html
from .summarize import summarize_rules, normalize_plain, extract_sections

log = logging.getLogger(__name__)

TRANS_CACHE_FILE = PROJECT_ROOT / "data" / "trans_cache.json"
if TRANS_CACHE_FILE.exists():
    try:
        trans_cache: Dict[str, str] = json.loads(TRANS_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        trans_cache = {}
else:
    trans_cache = {}

TIMEOUT = httpx.Timeout(30.0, connect=15.0)  # Увеличили timeout

# Языковые настройки по регионам (для Accept-Language)
_DEFAULT_LANG_BY_REGION = {
    "EU": "en-GB,en;q=0.9",
    "MD": "en-GB,en;q=0.9,ro;q=0.8,ru;q=0.7",
    "GLOBAL": "en-US,en;q=0.9",
}

def _get_proxy_for_region(region: str, proxy_country: Optional[str] = None, session_id: Optional[str] = None) -> Optional[Dict[str, str]]:
    """
    Возвращает настройки прокси для httpx в зависимости от региона источника.
    
    Параметры:
    - region: EU, MD или GLOBAL
    - proxy_country: переопределение страны для прокси (из config.json источника)
    - session_id: для sticky-сессий (Froxy поддерживает session=<rand>)
    """
    log.debug(f"🔍 DEBUG: _get_proxy_for_region({region}, USE_PROXY={USE_PROXY}, PROXY_URL={bool(PROXY_URL)}, PROXY_URL_EU={bool(PROXY_URL_EU)})")
    
    if not USE_PROXY:
        log.debug(f"🚫 USE_PROXY=False, возвращаем None")
        return None
    
    # Приоритет SOCKS5 над HTTP (для обхода блокировок Railway)
    if region == "MD" and SOCKS5_URL:
        base_url = SOCKS5_URL
        is_socks = True
    elif region == "EU" and SOCKS5_URL_EU:
        base_url = SOCKS5_URL_EU
        is_socks = True
    elif SOCKS5_URL:
        base_url = SOCKS5_URL
        is_socks = True
    elif region == "MD" and PROXY_URL:
        base_url = PROXY_URL
        is_socks = False
    elif region == "EU" and PROXY_URL_EU:
        base_url = PROXY_URL_EU
        is_socks = False
    elif PROXY_URL:
        base_url = PROXY_URL
        is_socks = False
    else:
        return None
    
    # Обработка Froxy прокси
    if PROXY_PROVIDER == "froxy":
        if PROXY_STICKY and session_id:
            # Добавляем session для sticky сессий
            modified_url = base_url.replace("@proxy.froxy.com", f":session={session_id}@proxy.froxy.com")
            log.debug(f"🔐 Froxy sticky session: region={region}, session={session_id}")
            return {"http://": modified_url, "https://": modified_url}
        else:
            log.debug(f"🔐 Froxy прокси: region={region}")
            return {"http://": base_url, "https://": base_url}
    else:
        # Другие прокси-провайдеры
        log.debug(f"🔐 Прокси: region={region}, provider={PROXY_PROVIDER}")
        return {"http://": base_url, "https://": base_url}


# Ротация User-Agent для более реалистичного поведения
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
]

def _fix_facebook_url(url: str) -> str:
    """
    Добавляет параметр _fb_noscript=1 к Facebook/Meta URL для обхода JavaScript редиректов
    """
    if any(domain in url for domain in ["facebook.com", "transparency.meta.com", "about.fb.com", "developers.facebook.com"]):
        # Проверяем если параметр уже есть
        if "_fb_noscript=1" not in url:
            # Добавляем параметр
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}_fb_noscript=1"
            log.debug(f"📋 Добавлен _fb_noscript к: {url}")
    return url

async def _fetch_with_curl_cffi(url: str, headers: dict, proxies: Optional[dict] = None, timeout: float = 30.0):
    """
    Адаптер для curl-cffi, который возвращает объект с интерфейсом httpx.Response
    """
    if not CURL_CFFI_AVAILABLE:
        raise ImportError("curl-cffi not available")
    
    class CurlCffiResponse:
        def __init__(self, response):
            self._response = response
            self.status_code = response.status_code
            self.text = response.text
            self.content = response.content
        
        def raise_for_status(self):
            if 400 <= self.status_code < 600:
                raise httpx.HTTPStatusError(f"{self.status_code} Error", request=None, response=self)
    
    # Преобразуем proxies из httpx формата в curl-cffi
    curl_proxies = None
    if proxies:
        # httpx: {"http://": "...", "https://": "..."} -> curl-cffi: {"http": "...", "https": "..."}
        proxy_url = proxies.get("http://", proxies.get("https://"))
        
        # Прокси уже в HTTP формате, используем как есть
        
        curl_proxies = {
            "http": proxy_url,
            "https": proxy_url
        }
    
    async with AsyncSession(
        impersonate="chrome120",  # TLS fingerprint Chrome 120
        verify=False,  # Отключаем проверку SSL
        timeout=timeout
    ) as session:
        response = await session.get(
            url,
            headers=headers,
            proxies=curl_proxies,
            allow_redirects=True
        )
        return CurlCffiResponse(response)

def _get_random_headers(url: str = "", accept_lang: Optional[str] = None):
    """Генерирует случайные заголовки для каждого запроса"""
    ua = random.choice(USER_AGENTS)
    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": accept_lang or "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "max-age=0",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Sec-CH-UA": '"Not_A Brand";v="8", "Chromium";v="131"',
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"Windows"',
    }
    
    # Специальные заголовки для Meta/Facebook сайтов
    if any(domain in url for domain in ["facebook.com", "transparency.meta.com", "about.fb.com", "developers.facebook.com"]):
        headers["Referer"] = "https://www.google.com/"
        headers["Sec-Fetch-Site"] = "cross-site"
        headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        # Убираем некоторые заголовки которые могут вызывать проблемы
        headers.pop("Sec-CH-UA", None)
        headers.pop("Sec-CH-UA-Mobile", None)
        headers.pop("Sec-CH-UA-Platform", None)
    
    # Дополнительные заголовки для WhatsApp
    elif "whatsapp.com" in url:
        headers["Referer"] = "https://www.google.com/"
        headers["Sec-Fetch-Site"] = "cross-site"
    
    return headers


FETCH_RETRIES = int(os.getenv("FETCH_RETRIES", "3"))
FETCH_RETRY_BACKOFF = float(os.getenv("FETCH_RETRY_BACKOFF", "1.2"))

LLM_MAX_CONCURRENCY = int(os.getenv("LLM_MAX_CONCURRENCY", "2"))
LLM_MIN_INTERVAL = float(os.getenv("LLM_MIN_INTERVAL", "0.3"))

# опциональная очистка кэша от удалённых источников (по умолчанию ВКЛ)
PRUNE_REMOVED_SOURCES = os.getenv("PRUNE_REMOVED_SOURCES", "1") == "1"

_llm_sem = asyncio.Semaphore(LLM_MAX_CONCURRENCY)
_llm_lock = asyncio.Lock()
_last_llm_ts: float = 0.0

_SENT_SPLIT_RE = r"(?<=[\.\!\?\n])\s+"

def _split_sentences(text: str) -> List[str]:
    t = (text or "").strip()
    if not t:
        return []
    t = re.sub(r"\s+", " ", t)
    parts = re.split(_SENT_SPLIT_RE, t)
    out = []
    for p in parts:
        p = p.strip(" -–—•\u00a0\t")
        if len(p) >= 2:
            out.append(p)
    return out

def _pair_changed_sentences(old_sents: List[str], new_sents: List[str], threshold: float = 0.0):
    matched_pairs: List[Tuple[str, str]] = []
    old_set = set(old_sents)
    new_set = set(new_sents)
    same = old_set & new_set

    old_only = [s for s in old_sents if s not in same]
    new_only = [s for s in new_sents if s not in same]

    used_new_idx: set[int] = set()
    for s_old in old_only:
        best_j = -1
        best_score = 0.0
        for j, s_new in enumerate(new_only):
            if j in used_new_idx:
                continue
            score = SequenceMatcher(None, s_old, s_new).ratio()
            if score > best_score:
                best_score = score
                best_j = j
        if best_score > threshold and best_j >= 0:
            matched_pairs.append((s_old, new_only[best_j]))
            used_new_idx.add(best_j)

    paired_old = {w for w, _ in matched_pairs}
    paired_new = {n for _, n in matched_pairs}
    old_only_final = [s for s in old_only if s not in paired_old]
    new_only_final = [s for s in new_only if s not in paired_new]

    return matched_pairs, old_only_final, new_only_final

def _clip_line(s: str, limit: int = 800) -> str:
    s = (s or "").strip()
    if len(s) <= limit:
        return s
    return s[:limit-1].rstrip() + "…"


async def _summarize_async(plain: str) -> str:
    global _last_llm_ts
    async with _llm_sem:
        async with _llm_lock:
            now = time.monotonic()
            wait = LLM_MIN_INTERVAL - (now - _last_llm_ts)
            if wait > 0:
                await asyncio.sleep(wait)
            _last_llm_ts = time.monotonic()
        return await asyncio.to_thread(summarize_rules, plain)

async def run_update() -> dict:
    log.info("🔄 Pipeline запущен - версия 2025-10-19-v4 с минимальными интервалами")
    
    # Проверка реального IP для диагностики прокси
    try:
        # IP без прокси (только для сравнения)
        try:
            if CURL_CFFI_AVAILABLE:
                r = await _fetch_with_curl_cffi("https://httpbin.org/ip", {}, None, 5.0)
                import json
                direct_ip = json.loads(r.text).get('origin')
            else:
                async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                    r = await client.get("https://httpbin.org/ip")
                    direct_ip = r.json().get('origin')
            log.info(f"🌎 Прямой IP Railway: {direct_ip}")
        except Exception as ip_e:
            direct_ip = "unknown"
            log.warning(f"⚠️ Ошибка проверки IP: {ip_e}")
        
        # IP через прокси
        if USE_PROXY:
            test_proxies = _get_proxy_for_region("GLOBAL", None, "ip_test")
            if test_proxies:
                try:
                    if CURL_CFFI_AVAILABLE:
                        r = await _fetch_with_curl_cffi("https://httpbin.org/ip", {}, test_proxies, 5.0)
                        import json
                        proxy_ip = json.loads(r.text).get('origin')
                    else:
                        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0), proxies=test_proxies, verify=False) as client:
                            r = await client.get("https://httpbin.org/ip")
                            proxy_ip = r.json().get('origin')
                    
                    log.info(f"🌎 IP через прокси: {proxy_ip}")
                    if direct_ip == proxy_ip:
                        log.warning(f"⚠️ ПРОКСИ НЕ РАБОТАЕТ! IP одинаковые: {direct_ip}")
                    else:
                        log.info(f"✅ Прокси работает! Прямой: {direct_ip}, Прокси: {proxy_ip}")
                except Exception as proxy_e:
                    log.warning(f"⚠️ Ошибка проверки прокси IP: {proxy_e}")
            else:
                log.warning("⚠️ Прокси конфиг не получен!")
    except Exception as e:
        log.warning(f"⚠️ Ошибка проверки IP: {e}")
    errors: List[Dict[str, Any]] = []
    details: List[Dict[str, Any]] = []

    cache_data = load_cache() or {}
    cache: List[Dict[str, Any]] = cache_data.get("items", [])
    # Ключ теперь (tag, url, region)
    idx: Dict[Tuple[str, str, str], int] = {
        (it.get("tag"), it.get("url"), it.get("region", "GLOBAL")): i 
        for i, it in enumerate(cache) if isinstance(it, dict)
    }

    changed_pages = 0
    changed_sections_total = 0

    # Генерируем session ID для sticky-сессий
    session_id = f"rand{random.randint(10000, 99999)}" if PROXY_STICKY else None
    
    # Для каждого источника будем создавать свой клиент с подходящим прокси
    for src_idx, src in enumerate(SOURCES):
        tag, url, title_hint = src.get("tag"), src.get("url"), src.get("title")
        region = src.get("region", "GLOBAL")
        custom_lang = src.get("lang")  # опциональный параметр
        proxy_country = src.get("proxy_country")  # опциональный параметр
        
        if not tag or not url:
            continue
        
        # Обрабатываем Facebook URL для обхода JavaScript редиректов
        url = _fix_facebook_url(url)
        
        # Минимальные задержки для резидентных прокси - максимальная эффективность
        if src_idx > 0:
            if "whatsapp.com" in url:
                delay = 2.0 + random.random() * 1.0  # 2-3 сек для WhatsApp
                log.info(f"💬 ⏳ WhatsApp: {delay:.1f} сек")
            else:
                # Минимальные интервалы с прокси - как на локалке
                delay = 0.5 + random.random() * 1.0  # 0.5-1.5 сек для Meta
                log.info(f"⏳ {delay:.1f} сек")
            await asyncio.sleep(delay)
        
        # Получаем прокси для региона источника
        proxies = _get_proxy_for_region(region, proxy_country, session_id)
        
        # Отладочное логирование прокси
        if proxies:
            proxy_url = proxies.get('https://') or proxies.get('http://', '')
            # Показываем только proxy.froxy.com:9000 для безопасности
            safe_proxy = proxy_url.split('@')[-1] if '@' in proxy_url else proxy_url
            log.info(f"🔐 Используется прокси для {region}: {safe_proxy}")
        else:
            log.warning(f"⚠️ Прокси НЕ ИСПОЛЬЗУЕТСЯ для {region} (proxies=None)")
        
        # Accept-Language по региону или кастомный
        accept_lang = custom_lang or _DEFAULT_LANG_BY_REGION.get(region, "en-US,en;q=0.9")
        headers = _get_random_headers(url, accept_lang)
        
        # SSL проверка: отключаем при прокси
        verify_ssl = proxies is None
        
        html = None
        used_fallback = False
        
        # Используем curl-cffi для ВСЕХ запросов через прокси
        use_curl_cffi = CURL_CFFI_AVAILABLE and USE_PROXY
        
        try:
            # Retry логика
            err = None
            for attempt in range(FETCH_RETRIES):
                try:
                    log.info(f"🔍 HTTP запрос attempt {attempt+1}/{FETCH_RETRIES} к {url} ({'curl-cffi' if use_curl_cffi else 'httpx'})")
                    
                    if use_curl_cffi:
                        timeout_seconds = TIMEOUT.total if hasattr(TIMEOUT, 'total') else 30.0
                        r = await _fetch_with_curl_cffi(url, headers, proxies, timeout_seconds)
                    else:
                        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True, proxies=proxies, verify=verify_ssl) as client:
                            r = await client.get(url, headers=headers)
                    
                    log.info(f"🔍 HTTP ответ: статус {r.status_code}, HTML: {len(r.text)} симв")
                    
                    # Особая обработка для статусов 400/422 - Meta сайты часто возвращают эти коды с валидным HTML
                    log.debug(f"🔍 DEBUG: Получили статус {r.status_code} для {url}")
                    if r.status_code in [400, 422]:
                        # Для Meta/Facebook сайтов принимаем любой ответ с содержимым
                        is_meta_site = any(domain in url for domain in ["transparency.meta.com", "facebook.com", "about.fb.com", "developers.facebook.com"])
                        log.info(f"🔍 {r.status_code} DEBUG: is_meta_site={is_meta_site}, HTML size={len(r.text) if r.text else 0}")
                        if is_meta_site and r.text and len(r.text.strip()) > 100:
                            log.info(f"✅ Meta сайт: Статус {r.status_code} но получен HTML ({len(r.text)} симв.), продолжаем")
                            html = r.text
                        elif r.text and len(r.text.strip()) > 500:
                            log.info(f"✅ Статус {r.status_code} но получен валидный HTML ({len(r.text)} симв.), продолжаем")
                            html = r.text
                        else:
                            log.warning(f"⚠️ Статус {r.status_code} с коротким ответом ({len(r.text) if r.text else 0} симв.), попробуем еще раз")
                            # НЕ вызываем raise_for_status для 400/422 - пусть retry цикл обработает
                            continue  # Пропускаем этот attempt и пробуем следующий
                    elif r.status_code in [200, 201, 202]:
                        html = r.text
                    else:
                        r.raise_for_status()
                        html = r.text
                    
                    # Проверка на блокировку
                    if "You're Temporarily Blocked" in html or "going too fast" in html:
                        if hasattr(r, 'request'):
                            raise httpx.HTTPStatusError("Temporary block", request=r.request, response=r)
                        else:
                            raise Exception("Temporary block detected")
                    
                    # Проверка на JavaScript редирект
                    if 'http-equiv="refresh"' in html and '_fb_noscript=1' in html:
                        # Получили страницу с редиректом, но уже с _fb_noscript - это ошибка
                        if hasattr(r, 'request'):
                            raise httpx.HTTPStatusError("JS redirect page despite _fb_noscript=1", request=r.request, response=r)
                        else:
                            raise Exception("JS redirect page despite _fb_noscript=1")
                    
                    elif 'http-equiv="refresh"' in html and 'URL=' in html:
                        # Обнаружен JavaScript редирект, попробуем с _fb_noscript=1
                        import re
                        redirect_match = re.search(r'URL=([^"]+)', html)
                        if redirect_match:
                            redirect_url = redirect_match.group(1)
                            if not redirect_url.startswith('http'):
                                # Относительный URL
                                from urllib.parse import urljoin
                                redirect_url = urljoin(url, redirect_url)
                            
                            log.info(f"🔄 JS редирект обнаружен, переходим на: {redirect_url}")
                            
                            if use_curl_cffi:
                                timeout_seconds = TIMEOUT.total if hasattr(TIMEOUT, 'total') else 30.0
                                r = await _fetch_with_curl_cffi(redirect_url, headers, proxies, timeout_seconds)
                            else:
                                # Для httpx создаем новый клиент
                                async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True, proxies=proxies, verify=verify_ssl) as redirect_client:
                                    r = await redirect_client.get(redirect_url, headers=headers)
                                    r.raise_for_status()
                            html = r.text
                    
                    break  # Успешно!
                except (httpx.HTTPStatusError, httpx.ProxyError, Exception) as e:
                    # Обработка ошибок для обоих httpx и curl-cffi
                    if isinstance(e, httpx.ProxyError):
                        # Пытаемся извлечь статус из сообщения
                        error_msg = str(e)
                        if '400' in error_msg:
                            status = 400
                        elif '422' in error_msg:
                            status = 422
                        elif '500' in error_msg:
                            status = 500
                        else:
                            status = 0
                        response_text = ''
                        log.info(f"🔍 ProxyError: сообщение='{error_msg}', извлечен статус={status}")
                    elif isinstance(e, httpx.HTTPStatusError):
                        status = getattr(e.response, 'status_code', 0) if hasattr(e, 'response') else 0
                        response_text = getattr(e.response, 'text', '') if hasattr(e, 'response') and e.response else ''
                        log.info(f"🔍 {type(e).__name__} пойман: статус {status}, HTML: {len(response_text)} симв")
                    else:
                        # Ошибки curl-cffi или другие
                        status = 0
                        response_text = ''
                        log.info(f"🔍 {type(e).__name__}: {str(e)}")
                    
                    # curl-cffi должен решить проблему TLS fingerprinting
                    if use_curl_cffi:
                        log.warning(f"⚠️ Ошибка с curl-cffi: {e}")
                    
                    # 407/403 для MD -> пробуем fallback на EU
                    if status in (407, 403) and region == "MD" and PROXY_FALLBACK_EU and PROXY_URL_EU and attempt == 0:
                        log.warning(f"⚠️ Ошибка {status} для MD прокси, переключаемся на EU fallback...")
                        # Переключаемся на EU прокси
                        proxies = _get_proxy_for_region("EU", proxy_country, session_id)
                        used_fallback = True
                        await asyncio.sleep(2)  # Быстрое переключение на EU
                        continue
                    
                    if status in (500, 502, 503, 429, 403, 407):
                        err = e
                        if attempt < FETCH_RETRIES - 1:
                            backoff = FETCH_RETRY_BACKOFF * (1.5 ** attempt) + random.random() * 2  # Быстрые retry
                            if status == 500:
                                log.warning(f"⚠️ Сервер Meta недоступен (500), попытка {attempt+1}/{FETCH_RETRIES}, ожидание {backoff:.1f} сек...")
                            else:
                                log.warning(f"⚠️ Ошибка {status} при загрузке {url}, попытка {attempt+1}/{FETCH_RETRIES}, ожидание {backoff:.1f} сек...")
                            await asyncio.sleep(backoff)
                            headers = _get_random_headers(url, accept_lang)
                        else:
                            if status == 429:
                                log.error(f"❌ Facebook заблокировал запросы: {url}. Пропускаем.")
                                err = None
                                break
                            raise
                    else:
                        raise
                else:
                    # Проверяем если HTML получен через fallback - не выбрасываем ошибку
                    if html:
                        log.info(f"✅ HTML получен через fallback, продолжаем обработку")
                        err = None  # Сбрасываем ошибку
                    elif err:
                        raise err
        except Exception as e:
            log.info(f"🔍 Внешний Exception пойман: {type(e).__name__}: {e}, HTML: {len(html) if html else 0} симв")
            # Проверяем, что не получили ли HTML во время 422 ошибки
            if html:
                log.info(f"✅ HTML получен несмотря на ошибку ({len(html)} симв.), продолжаем обработку")
            else:
                log.error("Ошибка при загрузке %s: %s", url, e)
                errors.append({"tag": tag, "url": url, "region": region, "error": str(e)})
                continue
        
        if not html:
            errors.append({"tag": tag, "url": url, "region": region, "error": "No HTML received"})
            continue
        
        if used_fallback:
            log.info(f"✅ Успешно получено через EU fallback: {url}")
        
        title_auto, full_plain, cleaned_html = clean_html(html, url)

        plain_norm = normalize_plain(full_plain or "")
        page_sig = compute_hash(plain_norm)

        sections_new = extract_sections(cleaned_html or html)
        sec_map_new = {s["id"]: s for s in sections_new if s.get("id")}

        key = (tag, url, region)
        existing_i = idx.get(key)
        existing = cache[existing_i] if existing_i is not None else None

        added_ids, removed_ids, modified_ids = [], [], []

        if existing:
            old_sections = existing.get("sections") or []
            sec_map_old = {s.get("id"): s for s in old_sections if s.get("id")}
            new_ids = set(sec_map_new.keys())
            old_ids = set(sec_map_old.keys())
            added_ids = list(new_ids - old_ids)
            removed_ids = list(old_ids - new_ids)
            modified_ids = [sid for sid in (new_ids & old_ids)
                            if sec_map_new[sid].get("sig") != sec_map_old[sid].get("sig")]
        else:
            added_ids = list(sec_map_new.keys())

        changed_here = bool(
            added_ids or removed_ids or modified_ids or
            (existing is None) or
            (existing and existing.get("hash") != page_sig)
        )
        if not changed_here:
            continue
        
        if page_sig in trans_cache:
            summary = trans_cache[page_sig]
        else:
            summary = await _summarize_async(full_plain or "")
            trans_cache[page_sig] = summary
        
        title = (title_hint or title_auto or "").strip() or url
        
        old_full = (existing or {}).get("full_text") or ""
        new_full = full_plain or ""
        old_sents = _split_sentences(old_full)
        new_sents = _split_sentences(new_full)
        pairs_global, old_only_global, new_only_global = _pair_changed_sentences(
            old_sents, new_sents, threshold=0.0
        )

        global_diff = {
            "changed": [{"was": _clip_line(w), "now": _clip_line(n)} for (w, n) in pairs_global],
            "removed": [_clip_line(s) for s in old_only_global],
            "added": [_clip_line(s) for s in new_only_global],
        }

        section_diffs: List[Dict[str, Any]] = []
        if added_ids:
            added_preview = []
            for sid in added_ids:
                sents = _split_sentences(sec_map_new[sid].get("text") or "")
                added_preview.append(_clip_line(sents[0] if sents else (sec_map_new[sid].get("title") or sid)))
            section_diffs.append({"type": "added", "title": "Добавлено", "added": added_preview})

        if removed_ids:
            removed_titles = []
            for sid in removed_ids:
                old_sec = next((s for s in (existing or {}).get("sections", []) if s.get("id") == sid), None)
                ttl = (old_sec or {}).get("title") or sid
                removed_titles.append(_clip_line(ttl))
            section_diffs.append({"type": "removed", "title": "Удалено", "removed": removed_titles})

        if modified_ids:
            for sid in modified_ids:
                old_s = next((s for s in (existing or {}).get("sections", []) if s.get("id") == sid), {})
                new_s = sec_map_new[sid]
                old_txt = old_s.get("text") or ""
                new_txt = new_s.get("text") or ""
                old_sents_s = _split_sentences(old_txt)
                new_sents_s = _split_sentences(new_txt)
                pairs_s, old_only_s, new_only_s = _pair_changed_sentences(
                    old_sents_s, new_sents_s, threshold=0.0
                )
                block = {
                    "type": "changed",
                    "title": new_s.get("title") or sid,
                    "changed": [{"was": _clip_line(w), "now": _clip_line(n)} for (w, n) in pairs_s]
                }
                if old_only_s:
                    block["removed_inline"] = [_clip_line(s) for s in old_only_s]
                if new_only_s:
                    block["added_inline"] = [_clip_line(s) for s in new_only_s]
                section_diffs.append(block)

        item = {
            "tag": tag,
            "url": url,
            "region": region,  # ✨ добавлен region
            "title": title,
            "summary": (summary or "").strip(),
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "hash": page_sig,
            "sections": sections_new,
            "full_text": new_full,
            "last_changed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

        if existing_i is not None:
            cache[existing_i] = item
        else:
            cache.append(item)
            idx[key] = len(cache) - 1
        
        changed_pages += 1
        changed_sections_total += len(added_ids) + len(modified_ids) + len(removed_ids)
        
        details.append({
            "tag": tag,
            "url": url,
            "region": region,  # ✨ добавлен region
            "title": title,
            "diff": {
                "added": [sec_map_new[sid].get("title") or sid for sid in added_ids],
                "modified": [sec_map_new[sid].get("title") or sid for sid in modified_ids],
                "removed": [
                    (next((s.get("title") for s in (existing or {}).get("sections", [])
                           if s.get("id") == sid), sid))
                    for sid in removed_ids
                ],
            },
            "global_diff": global_diff,
            "section_diffs": section_diffs
        })

    # 🔧 опционально чистим кэш от источников, которых больше нет в config.json
    if PRUNE_REMOVED_SOURCES:
        # Ключ теперь (tag, url, region)
        valid_tuples = {(s.get("tag"), s.get("url"), s.get("region", "GLOBAL")) for s in SOURCES if s.get("tag") and s.get("url")}
        cache = [it for it in cache if (it.get("tag"), it.get("url"), it.get("region", "GLOBAL")) in valid_tuples]

    stats = get_cache_stats()
    cache.sort(key=lambda x: x.get("ts", ""), reverse=True)
    if stats.get("max_cache") and len(cache) > stats["max_cache"]:
        cache = cache[:stats["max_cache"]]

    cache_data["items"] = cache
    save_cache(cache_data)

    try:
        tmp = TRANS_CACHE_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as tf:
            json.dump(trans_cache, tf, ensure_ascii=False, indent=2)
        os.replace(tmp, TRANS_CACHE_FILE)
    except Exception as e:
        log.error("Не удалось сохранить кэш переводов: %s", e)

    return {
        "changed": changed_pages,
        "errors": errors,
        "sections_total_changed": changed_sections_total,
        "details": details,
    }

def get_stats() -> dict:
    return get_cache_stats()
