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

from .storage import load_cache, save_cache, compute_hash, get_cache_stats
from .config import PROJECT_ROOT, SOURCES
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

# Настройки прокси из переменных окружения
PROXY_HOST = os.getenv("PROXY_HOST", "")
PROXY_USER = os.getenv("PROXY_USER", "")
PROXY_PASSWORD = os.getenv("PROXY_PASSWORD", "")

def _get_proxy_config(session_id: Optional[str] = None) -> Optional[Dict[str, str]]:
    """
    Возвращает настройки прокси для httpx, если они настроены.
    
    Параметры:
    - session_id: ИД сессии для BrightData (использует один IP для всех запросов)
    """
    if PROXY_HOST and PROXY_USER and PROXY_PASSWORD:
        proxy_user = PROXY_USER
        
        # Добавляем привязку к стране и session ID
        if "-country-" not in proxy_user:
            # Если нет указания страны - добавляем TARGET_REGION
            country_code = TARGET_REGION.lower() if TARGET_REGION != "AUTO" else "md"
            proxy_user = f"{proxy_user}-country-{country_code}"
        
        # Добавляем session ID для использования одного IP
        if session_id and "-session-" not in proxy_user:
            proxy_user = f"{proxy_user}-session-{session_id}"
        
        proxy_url = f"http://{proxy_user}:{PROXY_PASSWORD}@{PROXY_HOST}"
        log.info(f"🔐 Используется прокси: {PROXY_HOST} (страна: {TARGET_REGION}, session: {session_id or 'нет'})")
        return {"http://": proxy_url, "https://": proxy_url}
    else:
        log.warning("⚠️ Прокси не настроен, запросы идут напрямую")
        return None

# Настройка региона (можно переопределить через переменную окружения)
TARGET_REGION = os.getenv("TARGET_REGION", "MD")  # MD=Moldova (EU), US=United States

# Языковые настройки по регионам
REGION_SETTINGS = {
    "MD": {
        "lang": "en-GB,en;q=0.9,ro;q=0.8,ru;q=0.7",  # English (UK/EU), Romanian, Russian
        "country": "MD",
        "timezone": "Europe/Chisinau"
    },
    "US": {
        "lang": "en-US,en;q=0.9",
        "country": "US",
        "timezone": "America/New_York"
    },
    "EU": {
        "lang": "en-GB,en;q=0.9",
        "country": "GB",  # UK as EU representative
        "timezone": "Europe/London"
    }
}

region_config = REGION_SETTINGS.get(TARGET_REGION, REGION_SETTINGS["MD"])

# Ротация User-Agent для более реалистичного поведения
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
]

def _get_random_headers(url: str = ""):
    """Генерирует случайные заголовки для каждого запроса"""
    ua = random.choice(USER_AGENTS)
    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": region_config["lang"],
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
    
    # Дополнительные заголовки для WhatsApp
    if "whatsapp.com" in url:
        headers["Referer"] = "https://www.google.com/"
        headers["Sec-Fetch-Site"] = "cross-site"
        # Эмулируем переход с Google
    
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
    errors: List[Dict[str, Any]] = []
    details: List[Dict[str, Any]] = []

    cache_data = load_cache() or {}
    cache: List[Dict[str, Any]] = cache_data.get("items", [])
    idx: Dict[Tuple[str, str], int] = {(it.get("tag"), it.get("url")): i for i, it in enumerate(cache) if isinstance(it, dict)}

    changed_pages = 0
    changed_sections_total = 0

    # Генерируем session ID для использования одного IP для всех запросов
    session_id = f"session_{int(time.time())}"
    
    # Получаем настройки прокси с session ID
    proxies = _get_proxy_config(session_id)
    
    # Отключаем проверку SSL если используется прокси (BrightData использует MITM)
    verify_ssl = proxies is None
    
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True, proxies=proxies, verify=verify_ssl) as client:
        for src_idx, src in enumerate(SOURCES):
            tag, url, title_hint = src.get("tag"), src.get("url"), src.get("title")
            if not tag or not url:
                continue

            # Увеличенные задержки для избежания блокировок "going too fast"
            if src_idx > 0:
                # Увеличенные задержки для WhatsApp (более строгие лимиты)
                if "whatsapp.com" in url:
                    delay = 45.0 + random.random() * 15.0  # 45-60 сек для WhatsApp
                    log.info(f"💬 ⏳ WhatsApp: ожидание {delay:.1f} сек (увеличенная пауза)...")
                else:
                    # Увеличенные задержки для остальных сайтов (избегаем "going too fast")
                    if random.random() < 0.5:
                        delay = 20.0 + random.random() * 10.0  # 20-30 сек
                    else:
                        delay = 30.0 + random.random() * 10.0  # 30-40 сек
                    log.info(f"⏳ Ожидание {delay:.1f} сек перед следующим запросом...")
                await asyncio.sleep(delay)

            # Используем случайные заголовки для каждого запроса (с учетом URL)
            headers = _get_random_headers(url)
            
            try:
                # Retry логика с разными заголовками и обработкой 502
                err = None
                for attempt in range(FETCH_RETRIES):
                    try:
                        r = await client.get(url, headers=headers)
                        r.raise_for_status()
                        html = r.text
                        
                        # Проверка на блокировку Facebook (временная блокировка)
                        if "You're Temporarily Blocked" in html or "going too fast" in html:
                            # Создаем псевдо-response для обработки
                            class TempBlockResponse:
                                status_code = 429
                                request = r.request
                            
                            class TempBlockError(httpx.HTTPStatusError):
                                def __init__(self):
                                    self.response = TempBlockResponse()
                                    super().__init__("Temporary block detected", request=r.request, response=self.response)
                            
                            raise TempBlockError()
                        
                        break  # Успешно!
                    except httpx.HTTPStatusError as e:
                        # Обработка 502, 403 и временных блокировок
                        status = getattr(e.response, 'status_code', 0) if hasattr(e, 'response') else 0
                        if status in (502, 503, 429, 403) or "Temporary block" in str(e):
                            err = e
                            if attempt < FETCH_RETRIES - 1:
                                # Экспоненциальная задержка при 502 и блокировках
                                backoff = FETCH_RETRY_BACKOFF * (3 ** attempt) + random.random() * 5
                                log.warning(f"⚠️ Ошибка {status} при загрузке {url}, попытка {attempt+1}/{FETCH_RETRIES}, ожидание {backoff:.1f} сек...")
                                await asyncio.sleep(backoff)
                                # Меняем заголовки для следующей попытки
                                headers = _get_random_headers(url)
                            else:
                                # Если это блокировка Facebook - просто пропускаем
                                if status == 429:
                                    log.error(f"❌ Facebook заблокировал запросы: {url}. Пропускаем.")
                                    # Пропускаем этот URL, не падаем
                                    err = None
                                    break
                                raise
                        else:
                            raise
                    except Exception as e:
                        err = e
                        if attempt < FETCH_RETRIES - 1:
                            backoff = FETCH_RETRY_BACKOFF * (2 ** attempt)
                            await asyncio.sleep(backoff)
                            # Меняем заголовки для следующей попытки
                            headers = _get_random_headers(url)
                        else:
                            raise
                else:
                    # Все попытки исчерпаны
                    if err:
                        raise err
                    # Если err = None, значит мы пропустили URL из-за блокировки
            except Exception as e:
                log.error("Ошибка при загрузке %s: %s", url, e)
                errors.append({"tag": tag, "url": url, "error": str(e)})
                continue
            
            # Если err = None и мы пропустили URL - переходим к следующему
            if err is None or not locals().get('html'):
                errors.append({"tag": tag, "url": url, "error": "Facebook temporary block"})
                continue

            title_auto, full_plain, cleaned_html = clean_html(html, url)

            plain_norm = normalize_plain(full_plain or "")
            page_sig = compute_hash(plain_norm)

            sections_new = extract_sections(cleaned_html or html)
            sec_map_new = {s["id"]: s for s in sections_new if s.get("id")}

            key = (tag, url)
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
        valid_pairs = {(s.get("tag"), s.get("url")) for s in SOURCES if s.get("tag") and s.get("url")}
        cache = [it for it in cache if (it.get("tag"), it.get("url")) in valid_pairs]

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
