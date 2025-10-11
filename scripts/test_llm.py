# -*- coding: utf-8 -*-
import os
import json
import requests
from dotenv import load_dotenv

load_dotenv(override=True)

API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")
BASE_URL = os.getenv("OPENROUTER_COMPAT_URL", "https://openrouter.ai/api/v1").rstrip("/") + "/chat/completions"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
    "HTTP-Referer": os.getenv("OPENROUTER_REFERRER", "https://example.com"),
    "X-Title": os.getenv("OPENROUTER_TITLE", "Meta News Bot"),
}

def main():
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "Ты тестовый ассистент. Отвечай очень коротко."},
            {"role": "user", "content": "ping"},
        ],
        "max_tokens": 10,
        "temperature": 0.0,
    }

    r = requests.post(BASE_URL, headers=HEADERS, data=json.dumps(payload), timeout=30)
    print("HTTP", r.status_code)
    try:
        data = r.json()
        print(json.dumps(data, indent=2, ensure_ascii=False))
        print("\nОтвет:", data["choices"][0]["message"]["content"])
    except Exception:
        print(r.text)

if __name__ == "__main__":
    main()
