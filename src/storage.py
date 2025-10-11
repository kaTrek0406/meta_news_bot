# src/storage.py
import json, os, hashlib, datetime, logging
from pathlib import Path
from .config import PAGE_SIZE, MAX_ITEMS_TOTAL, SOURCES  # ← динамически берём список источников

log = logging.getLogger(__name__)

# Импорт модуля резервного копирования (опционально)
try:
    from .backup_storage import backup_to_gist, restore_from_gist, BACKUP_ENABLED
except ImportError:
    BACKUP_ENABLED = False
    def backup_to_gist(data): return False
    def restore_from_gist(): return None

ROOT = Path(os.getenv("PROJECT_ROOT") or Path(__file__).resolve().parents[1])
DATA_DIR = ROOT / "data" / "cache"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CACHE_FILE = DATA_DIR / "cache.json"

def _now_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def load_cache() -> dict:
    # Сначала пробуем загрузить из локального файла
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
    
    # Если локального файла нет, пробуем восстановить из Gist
    if BACKUP_ENABLED:
        log.info("Локальный кэш не найден, пытаюсь восстановить из GitHub Gist...")
        gist_data = restore_from_gist()
        if gist_data:
            # Сохраняем восстановленные данные локально
            try:
                save_cache(gist_data)
                log.info("Кэш восстановлен из Gist и сохранён локально")
                return gist_data
            except Exception as e:
                log.error(f"Ошибка сохранения восстановленного кэша: {e}")
                return gist_data
    
    return {"items": []}

def save_cache(data: dict) -> None:
    # Атомарная запись JSON (временный файл + переименование)
    tmp_file = CACHE_FILE.with_suffix('.tmp')
    try:
        with open(tmp_file, 'w', encoding='utf-8') as tf:
            json.dump(data, tf, ensure_ascii=False, indent=2)
        os.replace(tmp_file, CACHE_FILE)
        
        # Автоматическое резервное копирование в Gist (если настроено)
        if BACKUP_ENABLED:
            backup_to_gist(data)
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
