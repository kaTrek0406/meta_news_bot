# -*- coding: utf-8 -*-
"""
Перестройка кэша: вызывает run_update() 1..N раз, показывает счётчики.
Импортирует src-модули через importlib по абсолютным путям, чтобы IDE не ругалась.
"""
import argparse
import asyncio
import json
import time
from pathlib import Path
import importlib.util
import types


ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
PIPELINE_PATH = SRC_DIR / "pipeline.py"
STORAGE_PATH = SRC_DIR / "storage.py"

CACHE_PATH = ROOT / "data" / "cache" / "cache.json"
CONFIG_PATH = ROOT / "config.json"


def _load_module(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Не удалось создать spec для {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def human_time(s: float) -> str:
    if s < 60:
        return f"{s:.1f}s"
    m, s2 = divmod(int(s), 60)
    if m < 60:
        return f"{m}m {s2}s"
    h, m2 = divmod(m, 60)
    return f"{h}h {m2}m"


def load_sources_total() -> int:
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return len(cfg.get("sources", []))
    except Exception:
        return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=1, help="сколько раз вызвать run_update() подряд")
    args = ap.parse_args()

    pipeline = _load_module("pipeline", PIPELINE_PATH)
    storage = _load_module("storage", STORAGE_PATH)

    total_sources = load_sources_total()
    print(f"Rebuild cache… sources={total_sources or 'unknown'} repeat={args.repeat}")

    t0 = time.time()
    added_total = 0
    for _ in range(max(1, args.repeat)):
        res = asyncio.run(pipeline.run_update())
        added_total += res["changed"]
    took = time.time() - t0

    try:
        data = storage.load_cache()
        total_cached = len(data.get("items", []))
    except Exception:
        total_cached = 0

    print(f"Done in {human_time(took)}. Added/updated: {added_total}, total cached: {total_cached}")


if __name__ == "__main__":
    main()
