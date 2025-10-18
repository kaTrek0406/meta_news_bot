import os
import logging
from pathlib import Path
from typing import Optional, Dict, List
from dotenv import load_dotenv

log = logging.getLogger(__name__)

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
ENV_FILE: Path = PROJECT_ROOT / ".env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")

# Прокси настройки
PROXY_URL: str = os.getenv("PROXY_URL", "")  # Полный URL прокси
PROXY_URL_EU: str = os.getenv("PROXY_URL_EU", "")  # Fallback для EU
USE_PROXY: bool = os.getenv("USE_PROXY", "0") == "1"
PROXY_PROVIDER: str = os.getenv("PROXY_PROVIDER", "froxy")  # froxy или другой
PROXY_STICKY: bool = os.getenv("PROXY_STICKY", "0") == "1"  # Sticky sessions
PROXY_FALLBACK_EU: bool = os.getenv("PROXY_FALLBACK_EU", "1") == "1"  # Fallback MD->EU

# --- каталоги ---
DATA_DIR: Path = PROJECT_ROOT / "data"
LOGS_DIR: Path = PROJECT_ROOT / "logs"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Чтение конфигурации из config.json
CONFIG_FILE: Path = PROJECT_ROOT / "config.json"
CONFIG_DATA: dict = {}
if CONFIG_FILE.exists():
    import json
    try:
        CONFIG_DATA = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        raise RuntimeError(f"Не удалось загрузить config.json: {e}")

# Параметры из config.json
PAGE_SIZE: int = CONFIG_DATA.get("PAGE_SIZE", 4)
SOURCE_CONFIGURED: int = len(CONFIG_DATA.get("sources", []))
SOURCES: list = CONFIG_DATA.get("sources", [])
MAX_ITEMS_TOTAL: Optional[int] = CONFIG_DATA.get("MAX_ITEMS_TOTAL")
MAX_ITEMS_PER_DAY: Optional[int] = CONFIG_DATA.get("MAX_ITEMS_PER_DAY")
BULLETS: Optional[int] = CONFIG_DATA.get("BULLETS")

# Селекторы, которые нужно вырезать из HTML перед нормализацией/хэшированием
IGNORE_SELECTORS: Dict[str, List[str]] = CONFIG_DATA.get("ignore_selectors", {})

def selectors_for(url: str) -> List[str]:
    """Вернуть список CSS-селекторов для вырезания шума для данного хоста."""
    from urllib.parse import urlparse
    host = (urlparse(url).netloc or "").lower()
    base = IGNORE_SELECTORS.get("default", [])
    host_sel = IGNORE_SELECTORS.get(host, [])
    # убрать дубли, сохранить порядок
    seen = set()
    out: List[str] = []
    for s in [*base, *host_sel]:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out

def ensure_telegram_token() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")
    if not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_CHAT_ID не задан (хотя бы один чат требуется)")
    chat_ids = [c.strip() for c in TELEGRAM_CHAT_ID.split(",") if c.strip()]
    if not chat_ids:
        raise RuntimeError("TELEGRAM_CHAT_ID пуст (хотя бы один чат требуется)")

def ensure_openrouter_key() -> None:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY не задан")

def validate_proxy_config() -> None:
    """Проверяет корректность настроек прокси"""
    if USE_PROXY:
        if not PROXY_URL:
            raise RuntimeError("USE_PROXY=1 но PROXY_URL не задан")
        # Базовая валидация URL
        if not PROXY_URL.startswith(("http://", "https://", "socks5://")):
            raise RuntimeError(f"PROXY_URL невалиден: {PROXY_URL[:20]}...")
        log.info(f"🔐 Прокси настроен: провайдер={PROXY_PROVIDER}, sticky={PROXY_STICKY}, fallback_EU={PROXY_FALLBACK_EU}")
    else:
        log.warning("⚠️ Прокси не используется (USE_PROXY=0)")

def log_config_summary() -> None:
    """Логирует конфигурацию без секретов"""
    log.info(f"📦 Проект: {PROJECT_ROOT}")
    log.info(f"📊 Источников настроено: {len(SOURCES)}")
    log.info(f"📝 Кэш: max_items={MAX_ITEMS_TOTAL}, page_size={PAGE_SIZE}")
    log.info(f"💬 Telegram: {len([c.strip() for c in TELEGRAM_CHAT_ID.split(',') if c.strip()])} чат(ов)")
    log.info(f"🤖 OpenRouter: {'✓' if OPENROUTER_API_KEY else '✗'}")
    validate_proxy_config()
