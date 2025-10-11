# -*- coding: utf-8 -*-
"""
Диагностика LLM без жёсткой зависимости от пакета src в PYTHONPATH.
Использует importlib для подгрузки src/llm_client.py по абсолютному пути.
"""
import os
from pathlib import Path
import importlib.util
import types


ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
LLM_CLIENT_PATH = SRC_DIR / "llm_client.py"


def _load_llm_client() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("llm_client", LLM_CLIENT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Не удалось создать spec для {LLM_CLIENT_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def main() -> None:
    env_path = ROOT / ".env"
    print("=== Диагностика LLM ===")
    print(f".env: {'найден' if env_path.exists() else 'не найден'} ({env_path})\n")

    keys = [
        "OPENROUTER_API_KEY",
        "OPENROUTER_SITE_URL",
        "OPENROUTER_SITE_TITLE",
        "LLM_TEMPERATURE",
        "LLM_MAX_TOKENS",
        "LLM_REQUEST_TIMEOUT",
        "LLM_RETRY_ATTEMPTS",
        "LLM_RETRY_BACKOFF_SECONDS",
        "PAID_FALLBACK_MAX_PER_RUN",
        "LLM_MODEL",
    ]

    print("ENV параметры:")
    for k in keys:
        v = os.getenv(k)
        if v and k.endswith("_API_KEY"):
            v = v[:8] + "…" + v[-4:]
        print(f"  {k} = {v}")
    print()

    # загрузим клиент
    llm_client = _load_llm_client()

    print("Тестовый запрос к LLM…")
    try:
        resp = llm_client.chat(prompt="Проверка связи. Ответь одним словом: OK.", system="Be terse.")
        print("Ответ LLM:", (resp or "").strip())
    except Exception as e:
        # ловим любые ошибки, включая LLMError
        print("ОШИБКА тестового вызова:", repr(e))


if __name__ == "__main__":
    main()
