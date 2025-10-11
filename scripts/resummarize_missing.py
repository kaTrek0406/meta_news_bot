# -*- coding: utf-8 -*-
"""
Пересуммаризация «слабых» записей в кэше.
Импортирует src-модули через importlib по абсолютным путям, чтобы IDE не ругалась.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import random
import time
from pathlib import Path
from typing import List, Dict, Any
import importlib.util
import types


ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
STORAGE_PATH = SRC_DIR / "storage.py"
FETCH_PATH = SRC_DIR / "fetch.py"
SUMMARIZE_PATH = SRC_DIR / "summarize.py"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("resummarize_missing")

STOP_PREFIXES = (
    "×",
    "Skip to",
    "Table of Contents",
    "News",
    "Back to Newsroom",
    "Help Center",
    "Conversations 2025",
)


def _load_module(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Не удалось создать spec для {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def _clean_points(lines: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for p in lines or []:
        p = (p or "").strip()
        if not p:
            continue
        low = p.lower()
        if low.startswith(tuple(s.lower() for s in STOP_PREFIXES)):
            continue
        if low in seen:
            continue
        seen.add(low)
        out.append(p)
    return out[:5]


def is_bad(item: Dict[str, Any]) -> bool:
    title: str = (item.get("title") or "").strip()
    summary: str = (item.get("summary") or "").strip()
    if not title:
        return True
    # считаем «слабым», если нет буллетов и лид слишком короткий
    has_bullets = any(ln.strip().startswith("-") for ln in summary.splitlines())
    if not has_bullets or len(summary) < 40:
        return True
    return False


def resummarize_item(item: Dict[str, Any], storage, fetch, summarize) -> bool:
    url = item.get("url") or ""
    if not url:
        return False
    log.info("Re-summarize: %s", url)

    html = asyncio.run(fetch.fetch_text(url))
    if not html:
        log.warning("Пустой ответ при загрузке: %s", url)
        return False

    _, plain = summarize.text_from_html(html)
    if not plain or len(plain.strip()) < 200:
        log.warning("Мало текста после извлечения: %s (len=%s)", url, len(plain or ""))

    summ = summarize.summarize_rules(plain)

    before = item.get("summary", "")
    item["summary"] = (summ or "").strip() or before

    # анти-429 — мягкая пауза 0.5–1.0 c
    time.sleep(0.5 + random.random() * 0.5)
    return item["summary"] != before


def main() -> None:
    storage = _load_module("storage", STORAGE_PATH)
    fetch = _load_module("fetch", FETCH_PATH)
    summarize = _load_module("summarize", SUMMARIZE_PATH)

    data = storage.load_cache()
    items = data.get("items", [])
    if not items:
        log.warning("Кэш пуст — нечего пересобирать.")
        return

    ap = argparse.ArgumentParser(description="Re-summarize weak/missing items in cache")
    ap.add_argument("--all", action="store_true", help="пересуммаризировать ВСЕ записи")
    ap.add_argument("--limit", type=int, default=50, help="максимум записей за один прогон")
    args = ap.parse_args()

    candidates = [it for it in items if args.all or is_bad(it)]
    if not candidates:
        log.info("Плохих/пустых записей не найдено.")
        return

    changed = 0
    processed = 0
    for item in candidates[: args.limit]:
        try:
            if resummarize_item(item, storage, fetch, summarize):
                changed += 1
            processed += 1
        except Exception as e:
            log.exception("Ошибка на %s: %s", item.get("url"), e)

    if changed:
        data["items"] = items
        storage.save_cache(data)

    log.info("Готово. Обработано: %s, обновлено: %s из %s", processed, changed, len(candidates))


if __name__ == "__main__":
    main()
