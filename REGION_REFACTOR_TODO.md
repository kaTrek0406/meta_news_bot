# Региональный рефакторинг - оставшиеся задачи

## ✅ Выполнено

1. ✅ Добавлен `region` в `config.json` для каждого источника
2. ✅ Обновлен `src/config.py` - добавлены настройки прокси и валидация
3. ✅ Модифицирован `src/pipeline.py` - поддержка region, Froxy, fallback MD→EU
4. ✅ Обновлен `src/storage.py` - автоматическое добавление region='GLOBAL' при загрузке
5. ✅ Создан `scripts/migrate_region_tag.py` - скрипт миграции

## 🔧 Осталось выполнить

### 1. Обновить `src/smart_formatter.py`

Добавить региональные эмодзи к заголовкам:

```python
# В начале файла добавить:
REGION_BADGES = {
    "EU": "🇪🇺 [EU]",
    "MD": "🇲🇩 [MD]",
    "GLOBAL": "🌍 [GLOBAL]",
}

# В функции _format_api_change и _format_policy_change добавить region:
def _format_api_change(detail: Dict) -> str:
    title = detail.get("title", "")
    url = detail.get("url", "")
    region = detail.get("region", "GLOBAL")  # ← добавить
    
    # ... существующий код ...
    
    # Заголовок с region badge
    region_badge = REGION_BADGES.get(region, "🌍 [GLOBAL]")
    output.append(f"{priority_icon} <b>{escape(title)}</b> {region_badge}")  # ← изменить
    # ... остальной код ...
```

### 2. Обновить `src/telegram_notify.py`

Добавить функцию группировки по регионам:

```python
def group_by_region(details: list) -> dict:
    """Группирует изменения по регионам в порядке EU → MD → GLOBAL"""
    grouped = {"EU": [], "MD": [], "GLOBAL": []}
    
    for detail in details:
        region = detail.get("region", "GLOBAL")
        if region in grouped:
            grouped[region].append(detail)
        else:
            grouped["GLOBAL"].append(detail)
    
    return grouped

async def notify_changes_grouped(details: list) -> None:
    """Отправляет сообщения, сгруппированные по регионам"""
    grouped = group_by_region(details)
    
    for region in ["EU", "MD", "GLOBAL"]:
        items = grouped[region]
        if not items:
            continue
        
        region_badge = {
            "EU": "🇪🇺 EU",
            "MD": "🇲🇩 MD",
            "GLOBAL": "🌍 GLOBAL"
        }.get(region, "🌍 GLOBAL")
        
        header = f"\n═══ {region_badge} ({len(items)}) ═══\n"
        
        # Форматируем и отправляем
        for item in items:
            # ... форматирование каждого item ...
            pass
```

### 3. Обновить `src/summarize.py`

Не требует изменений - работает как есть.

### 4. Обновить `src/tg/handlers.py`

Добавить region статистику в команду `/status`:

```python
from collections import Counter

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... существующий код ...
    
    # Статистика по регионам
    items = storage.get_items()
    region_counts = Counter(item.get("region", "GLOBAL") for item in items)
    
    # Изменения за 24ч по регионам
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)
    
    recent_by_region = {"EU": 0, "MD": 0, "GLOBAL": 0}
    for item in items:
        ts_str = item.get("last_changed_at") or item.get("ts")
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts >= day_ago:
                    region = item.get("region", "GLOBAL")
                    recent_by_region[region] = recent_by_region.get(region, 0) + 1
            except:
                pass
    
    status_text = [
        "📊 <b>Статус по регионам</b>\n",
        f"🇪🇺 <b>EU</b> — источников: {region_counts.get('EU', 0)}, изменений за 24ч: {recent_by_region['EU']}",
        f"🇲🇩 <b>MD</b> — источников: {region_counts.get('MD', 0)}, изменений за 24ч: {recent_by_region['MD']}",
        f"🌍 <b>GLOBAL</b> — источников: {region_counts.get('GLOBAL', 0)}, изменений за 24ч: {recent_by_region['GLOBAL']}",
        "",
        f"Всего источников: {len(SOURCES)}",
        f"Последнее обновление: {stats.get('latest_utc', 'нет данных')}",
        "",
        "🔧 <b>Системные флаги:</b>",
        f"USE_PROXY: {config.USE_PROXY}",
        f"PROXY_PROVIDER: {config.PROXY_PROVIDER}",
        f"PROXY_STICKY: {config.PROXY_STICKY}",
        f"PROXY_FALLBACK_EU: {config.PROXY_FALLBACK_EU}",
    ]
    
    await update.message.reply_text("\n".join(status_text), parse_mode="HTML")
```

## 📝 Настройки .env

Добавить в `.env`:

```ini
# Прокси настройки (Froxy)
USE_PROXY=1
PROXY_URL=http://wifi;md;;:PASSWORD@proxy.froxy.com:9000
PROXY_URL_EU=http://wifi;de;;:PASSWORD@proxy.froxy.com:9000
PROXY_PROVIDER=froxy
PROXY_STICKY=1
PROXY_FALLBACK_EU=1
```

## 🚀 Запуск миграции

После обновления кода запустить:

```bash
python scripts/migrate_region_tag.py
```

Это добавит `region='GLOBAL'` ко всем старым записям в кэше.

## 🧪 Тестирование

1. Проверить, что все источники в `config.json` имеют `region`
2. Запустить `python scripts/migrate_region_tag.py`
3. Запустить бота и проверить `/status`
4. Проверить, что изменения группируются по регионам в Telegram
5. Проверить fallback MD→EU при ошибках прокси

## 📌 Примечания

- Старые записи автоматически получают `region='GLOBAL'` при загрузке
- Ключ кэша теперь `(tag, url, region)` вместо `(tag, url)`
- Froxy поддерживает sticky-сессии через `session=<rand>` в пароле
- При 407/403 с MD прокси автоматически переключается на EU (если `PROXY_FALLBACK_EU=1`)
