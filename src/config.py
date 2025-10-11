import os
from pathlib import Path
from typing import Optional, Dict, List
from dotenv import load_dotenv

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
ENV_FILE: Path = PROJECT_ROOT / ".env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")

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

def ensure_openrouter_key() -> None:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY не задан")
