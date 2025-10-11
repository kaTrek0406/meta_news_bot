# src/storage.py
import json, os, hashlib, datetime
from pathlib import Path
from .config import PAGE_SIZE, MAX_ITEMS_TOTAL, SOURCES  # ← динамически берём список источников

ROOT = Path(os.getenv("PROJECT_ROOT") or Path(__file__).resolve().parents[1])
DATA_DIR = ROOT / "data" / "cache"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CACHE_FILE = DATA_DIR / "cache.json"

def _now_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            # ✅ Back-compat: раньше cache.json был списком; теперь — {"items":[...]}
            if isinstance(data, list):
                data = {"items": data}
            elif not isinstance(data, dict):
                data = {"items": []}
            # гарантия ключа
            if "items" not in data or not isinstance(data["items"], list):
                data["items"] = []
            return data
        except Exception:
            pass
    return {"items": []}

def save_cache(data: dict) -> None:
    # Атомарная запись JSON (временный файл + переименование)
    tmp_file = CACHE_FILE.with_suffix('.tmp')
    try:
        with open(tmp_file, 'w', encoding='utf-8') as tf:
            json.dump(data, tf, ensure_ascii=False, indent=2)
        os.replace(tmp_file, CACHE_FILE)
    except Exception:
        raise

def compute_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()

def get_items() -> list:
    return load_cache().get("items", [])

def get_cache_stats() -> dict:
    """Возвращает статистику кэша. Число источников — по текущему config.SOURCES."""
    data = load_cache()
    items = data.get("items", []) if data else []
    sources_configured = len(SOURCES)  # ← динамически, отражает актуальный config.json
    page_size = PAGE_SIZE
    max_cache = MAX_ITEMS_TOTAL or len(items)

    latest = None
    for it in items:
        ts = it.get("ts")
        if ts:
            try:
                dt = datetime.datetime.fromisoformat(ts)
            except Exception:
                continue
            if not latest or dt > latest:
                latest = dt
    latest_iso = latest.isoformat(timespec="seconds") if latest else datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    return {
        "sources_configured": sources_configured,
        "items_cached": len(items),
        "latest_utc": latest_iso,
        "page_size": page_size,
        "max_cache": max_cache
    }
