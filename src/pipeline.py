# -*- coding: utf-8 -*-
import logging
import os
import json
import time
import random
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Any

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
# Используем современный User-Agent и явно указываем английский язык
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Cache-Control": "max-age=0",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Sec-CH-UA": '"Not_A Brand";v="8", "Chromium";v="131", "Google Chrome";v="131"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Windows"',
}

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

async def _http_get_with_retries(client: httpx.AsyncClient, url: str) -> str:
    err: Exception | None = None
    for attempt in range(FETCH_RETRIES):
        try:
            r = await client.get(url)
            r.raise_for_status()
            return r.text
        except Exception as e:
            err = e
            backoff = FETCH_RETRY_BACKOFF * (2 ** attempt)
            await asyncio.sleep(backoff)
    raise err if err else RuntimeError("unknown http error")

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

    async with httpx.AsyncClient(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True) as client:
        for src_idx, src in enumerate(SOURCES):
            tag, url, title_hint = src.get("tag"), src.get("url"), src.get("title")
            if not tag or not url:
                continue

            # Задержка между запросами для избежания блокировок (2-4 секунды)
            if src_idx > 0:
                delay = 2.0 + random.random() * 2.0
                await asyncio.sleep(delay)

            try:
                html = await _http_get_with_retries(client, url)
            except Exception as e:
                log.error("Ошибка при загрузке %s: %s", url, e)
                errors.append({"tag": tag, "url": url, "error": str(e)})
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
