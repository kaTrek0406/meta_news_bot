# -*- coding: utf-8 -*-
import os, time, random, logging, requests

log = logging.getLogger(__name__)

API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")
BASE_URL = os.getenv("OPENROUTER_COMPAT_URL", "https://openrouter.ai/api/v1").rstrip("/") + "/chat/completions"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_DEV_CHAT_ID = os.getenv("TELEGRAM_DEV_CHAT_ID", "")  # новый

LLM_REQUEST_TIMEOUT = int(os.getenv("LLM_REQUEST_TIMEOUT", "60"))
LLM_RETRY_ATTEMPTS = int(os.getenv("LLM_RETRY_ATTEMPTS", "5"))
LLM_RETRY_BACKOFF_SECONDS = float(os.getenv("LLM_RETRY_BACKOFF_SECONDS", "1.2"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "800"))

SYSTEM_SUMMARY = "Ты помощник, который кратко структурирует правила и изменения Meta/Ads."

class LLMError(Exception):
    pass

def _first_chat_id(s: str) -> str:
    parts = [p.strip() for p in (s or "").split(",") if p.strip()]
    return parts[0] if parts else ""

def _notify_error(msg: str):
    if not TELEGRAM_TOKEN:
        return
    chat_id = TELEGRAM_DEV_CHAT_ID.strip() or _first_chat_id(TELEGRAM_CHAT_ID)
    if not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": f"⚠️ Ошибка LLM:\n{msg[:3000]}"},
                      timeout=10)
    except Exception as e:
        log.error("Не удалось отправить уведомление: %s", e)

def _post_json(payload: dict) -> dict:
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "https://example.com"),
        "X-Title": os.getenv("OPENROUTER_SITE_TITLE", "Meta News Bot"),
    }
    backoff = LLM_RETRY_BACKOFF_SECONDS
    attempts = LLM_RETRY_ATTEMPTS
    for i in range(attempts):
        try:
            r = requests.post(BASE_URL, headers=headers, json=payload, timeout=LLM_REQUEST_TIMEOUT)
            if r.status_code in (429, 500, 502, 503, 504):
                raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if i == attempts - 1:
                _notify_error(f"{MODEL} ошибка: {e}")
                raise
            delay = backoff * (2 ** i) + random.random() * 0.2
            time.sleep(delay)
    raise LLMError("Не удалось выполнить запрос к LLM после ретраев")

def chat(prompt: str, system: str = SYSTEM_SUMMARY) -> str:
    if not API_KEY:
        raise LLMError("Не задан OPENROUTER_API_KEY")
    prompt = (prompt or "")[:6000]
    payload = {
        "model": MODEL,
        "max_tokens": LLM_MAX_TOKENS,
        "temperature": LLM_TEMPERATURE,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    }
    data = _post_json(payload)
    try:
        return (data["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:
        err = f"Неверный ответ от модели: {e}, raw={str(data)[:400]}"
        _notify_error(err)
        raise LLMError(err)

def summarize_rules(html: str) -> str:
    prompt = f"Суммируй изменения/правила из этого HTML:\n\n{html}"
    return chat(prompt, system=SYSTEM_SUMMARY)

def translate_compact_html(html: str, target_lang: str = "ru", max_len: int | None = None) -> str:
    max_len = max_len or 1400
    system = "Ты редактор. Держи разметку HTML, пиши кратко и по-русски."
    prompt = (
        "Переведи следующий HTML на {lang} и ужми текст так, чтобы он оставался читаемым в Telegram:\n"
        "— Сохраняй существующие HTML-теги (<b>, <i>, <a>, переносы строк) и не добавляй новые.\n"
        "— Сохраняй структуру пунктов (— , ➕, ➖, ✏️) и заголовок.\n"
        "— Укорачивай однотипные длинные списки: оставь самые важные 5–8 пунктов.\n"
        "— Убери служебные хвосты и куки-баннеры.\n"
        f"— Общая длина результата ≤ {max_len} символов.\n\n"
        f"HTML:\n{html}"
    ).format(lang=target_lang)
    return chat(prompt=prompt, system=system)
