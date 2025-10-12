# meta_news_bot_json (Telegram + JSON storage)

Бот парсит официальные страницы Meta (правила/политики), сокращает и **переводит на русский** через DeepSeek (OpenRouter),
хранит состояние в **JSON-файлах**, без БД.

## Быстрый старт (Windows)

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# откройте .env, вставьте свой TELEGRAM_BOT_TOKEN и OPENROUTER_API_KEY
python -m src.main
```

## Команды
- `/start` — меню и кнопки по тегам
- `/latest` — последние за N дней
- `/debug` — тестовый вызов DeepSeek
- `/unsubscribe` — отписаться

## Конфиг
- `config.json` — окно дней, лимиты, размер страницы, теги.
- `.env` — токены: `TELEGRAM_BOT_TOKEN`, `OPENROUTER_API_KEY`.

## Настройка прокси (опционально)

Для обхода блокировок Facebook на облачных хостингах (Railway, AWS и т.д.) можно использовать residential прокси.

Добавьте в `.env` или переменные окружения Railway:
```
PROXY_HOST=brd.superproxy.io:33335
PROXY_USER=brd-customer-hl_3967120c-zone-residential_proxy1
PROXY_PASSWORD=viv0l29v3tb2
```

**Примечание:** Если переменные не указаны, бот работает без прокси (подходит для локального запуска).

## Хранилище
- `data/items.json` — сохранённые материалы: url, tag, hash, summary_ru, дата.
- `data/cache.json` — ETag/Last-Modified для источников.
