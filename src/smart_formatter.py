# -*- coding: utf-8 -*-
"""
Интеллектуальное форматирование изменений для таргетологов.
Анализирует изменения и предоставляет конкретные рекомендации.
"""

import logging
import re
from typing import Dict, List, Tuple
from html import escape

log = logging.getLogger(__name__)

# Региональные бейджи (флаги + теги)
REGION_BADGES = {
    "EU": "🇪🇺 [EU]",
    "MD": "🇲🇩 [MD]",
    "GLOBAL": "🌍 [GLOBAL]",
}

# Ключевые слова для определения важности изменений
TARGETING_KEYWORDS = {
    "критично": [
        "discontinued", "removed", "deprecated", "no longer available", "will be retired",
        "удалено", "больше не доступно", "прекращено", "отключено",
        "restricted", "prohibited", "banned", "запрещено", "ограничено"
    ],
    "важно": [
        "new", "added", "introduced", "available", "support", "launch",
        "новый", "добавлен", "доступен", "запуск", "поддержка",
        "update", "change", "modify", "обновление", "изменение",
        "targeting", "audience", "placement", "таргетинг", "аудитория", "размещение",
        "api", "endpoint", "field", "parameter"
    ],
    "информация": [
        "date", "version", "documentation", "example",
        "дата", "версия", "документация", "пример"
    ]
}

# Категории изменений
IMPACT_CATEGORIES = {
    "api": ["api", "endpoint", "field", "parameter", "method", "request", "response"],
    "targeting": ["targeting", "audience", "geo", "location", "demographic", "interest", "behavior", 
                  "таргетинг", "аудитория", "геолокация"],
    "placement": ["placement", "messenger", "instagram", "facebook", "stories", "reels", "feed",
                  "размещение", "позиция"],
    "budget": ["budget", "bid", "cost", "price", "billing", "payment", "бюджет", "ставка", "цена"],
    "format": ["format", "creative", "image", "video", "carousel", "формат", "креатив"],
    "policy": ["policy", "prohibited", "restricted", "compliance", "политика", "запрещено", "соответствие"],
    "reporting": ["insight", "metric", "report", "analytics", "attribution", "отчёт", "метрика", "аналитика"],
}


def _normalize_text(text: str) -> str:
    """Нормализует текст для сравнения"""
    return re.sub(r'\s+', ' ', (text or "").strip().lower())


def _extract_key_changes(was: str, now: str) -> List[str]:
    """Извлекает ключевые отличия между двумя текстами"""
    was_norm = _normalize_text(was)
    now_norm = _normalize_text(now)
    
    # Извлекаем даты
    date_pattern = r'\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|янв|фев|мар|апр|май|июн|июл|авг|сен|окт|ноя|дек)[a-zа-я]*\s+\d{4}\b'
    dates_was = set(re.findall(date_pattern, was_norm))
    dates_now = set(re.findall(date_pattern, now_norm))
    
    changes = []
    
    # Изменение дат
    if dates_now - dates_was:
        new_dates = ", ".join(dates_now - dates_was)
        changes.append(f"Обновлена дата: {new_dates}")
    
    # Новые эндпоинты/поля
    endpoint_pattern = r'(?:GET|POST|DELETE|PUT)\s+/\{[^}]+\}'
    endpoints_was = set(re.findall(endpoint_pattern, was))
    endpoints_now = set(re.findall(endpoint_pattern, now))
    
    if endpoints_now - endpoints_was:
        for ep in endpoints_now - endpoints_was:
            changes.append(f"Новый эндпоинт: {ep}")
    
    if endpoints_was - endpoints_now:
        for ep in endpoints_was - endpoints_now:
            changes.append(f"Удалён эндпоинт: {ep}")
    
    # Поиск конкретных изменений
    if "no longer available" in now_norm and "no longer available" not in was_norm:
        changes.append("⚠️ Функция больше не доступна")
    
    if "applies to all versions" in now_norm and "applies to all versions" not in was_norm:
        changes.append("⚠️ Применяется ко ВСЕМ версиям API")
    
    # Ищем новые ограничения
    if "limited to" in now_norm and "limited to" not in was_norm:
        limitation = re.search(r'limited to (\d+\s+\w+)', now_norm)
        if limitation:
            changes.append(f"⚠️ Новое ограничение: {limitation.group(1)}")
    
    return changes


def _detect_impact_category(text: str) -> str:
    """Определяет категорию влияния изменения"""
    text_lower = text.lower()
    
    for category, keywords in IMPACT_CATEGORIES.items():
        for kw in keywords:
            if kw in text_lower:
                return category
    
    return "general"


def _assess_priority(was: str, now: str, added: List[str], removed: List[str]) -> Tuple[str, str]:
    """
    Оценивает приоритет изменения
    Возвращает (уровень, иконка)
    """
    combined_text = f"{was} {now} {' '.join(added)} {' '.join(removed)}".lower()
    
    # Критично
    for kw in TARGETING_KEYWORDS["критично"]:
        if kw in combined_text:
            return ("🔴 КРИТИЧНО", "🔴")
    
    # Важно
    for kw in TARGETING_KEYWORDS["важно"]:
        if kw in combined_text:
            return ("🟡 ВАЖНО", "🟡")
    
    # Информация
    return ("🟢 Инфо", "🟢")


def _format_api_change(detail: Dict) -> str:
    """Специальное форматирование для API изменений"""
    title = detail.get("title", "")
    url = detail.get("url", "")
    region = detail.get("region", "GLOBAL")
    
    gd = detail.get("global_diff") or {}
    changed = gd.get("changed") or []
    added = gd.get("added") or []
    removed = gd.get("removed") or []
    
    output = []
    
    # Заголовок с приоритетом
    priority_text, priority_icon = _assess_priority(
        " ".join([p.get("was", "") for p in changed]),
        " ".join([p.get("now", "") for p in changed]),
        added,
        removed
    )
    
    region_badge = REGION_BADGES.get(region, "🌍 [GLOBAL]")
    output.append(f"{priority_icon} <b>{escape(title)}</b> {region_badge}")
    output.append(f"Приоритет: {priority_text}")
    output.append("")
    
    # Анализируем изменения
    key_changes = []
    for pair in changed:
        was = pair.get("was", "")
        now = pair.get("now", "")
        extracted = _extract_key_changes(was, now)
        key_changes.extend(extracted)
    
    if key_changes:
        output.append("<b>📝 Что изменилось:</b>")
        for change in key_changes[:5]:  # Максимум 5 ключевых изменений
            output.append(f"• {escape(change)}")
        output.append("")
    
    # Новые возможности
    if added:
        output.append("<b>➕ Добавлено:</b>")
        for item in added[:3]:  # Топ-3
            item_text = item.strip()
            if len(item_text) > 150:
                item_text = item_text[:147] + "..."
            output.append(f"• {escape(item_text)}")
        if len(added) > 3:
            output.append(f"<i>... и ещё {len(added) - 3}</i>")
        output.append("")
    
    # Удалённые элементы
    if removed:
        output.append("<b>➖ Удалено:</b>")
        for item in removed[:3]:
            item_text = item.strip()
            if len(item_text) > 150:
                item_text = item_text[:147] + "..."
            output.append(f"• {escape(item_text)}")
        if len(removed) > 3:
            output.append(f"<i>... и ещё {len(removed) - 3}</i>")
        output.append("")
    
    # Рекомендации
    impact_cat = _detect_impact_category(title + " " + str(changed))
    recommendations = _get_recommendations(impact_cat, priority_text, added, removed, changed)
    
    if recommendations:
        output.append("<b>💡 Рекомендации:</b>")
        for rec in recommendations:
            output.append(f"• {rec}")
        output.append("")
    
    # Ссылка
    if url:
        output.append(f"🔗 {escape(url)}")
    
    return "\n".join(output)


def _format_policy_change(detail: Dict) -> str:
    """Специальное форматирование для изменений политик"""
    title = detail.get("title", "")
    url = detail.get("url", "")
    region = detail.get("region", "GLOBAL")
    
    gd = detail.get("global_diff") or {}
    changed = gd.get("changed") or []
    
    output = []
    
    # Определяем приоритет
    priority_text, priority_icon = _assess_priority(
        " ".join([p.get("was", "") for p in changed]),
        " ".join([p.get("now", "") for p in changed]),
        [],
        []
    )
    
    region_badge = REGION_BADGES.get(region, "🌍 [GLOBAL]")
    output.append(f"{priority_icon} <b>{escape(title)}</b> {region_badge}")
    
    # Для политик важно показать, что именно изменилось в правилах
    has_meaningful_change = False
    
    for pair in changed:
        was = _normalize_text(pair.get("was", ""))
        now = _normalize_text(pair.get("now", ""))
        
        # Игнорируем изменения только в датах
        was_no_dates = re.sub(r'\d+\s+\w+\s+\d{4}', '', was)
        now_no_dates = re.sub(r'\d+\s+\w+\s+\d{4}', '', now)
        
        if was_no_dates != now_no_dates:
            has_meaningful_change = True
            break
    
    if not has_meaningful_change:
        # Только обновление даты
        output.append("")
        output.append("ℹ️ <i>Обновлена дата документа, содержание без изменений</i>")
    else:
        output.append("")
        output.append("<b>⚠️ Изменены правила политики!</b>")
        output.append("")
        output.append("<b>💡 Действия:</b>")
        output.append("• Проверьте текущие кампании на соответствие")
        output.append("• Обновите креативы если требуется")
        output.append("• Ознакомьтесь с полным текстом изменений")
    
    output.append("")
    if url:
        output.append(f"🔗 {escape(url)}")
    
    return "\n".join(output)


def _get_recommendations(category: str, priority: str, added: List[str], removed: List[str], changed: List[Dict]) -> List[str]:
    """Генерирует рекомендации на основе категории и приоритета"""
    recs = []
    
    if "КРИТИЧНО" in priority:
        if category == "api":
            recs.append("⚠️ Срочно обновите интеграцию до изменений")
            recs.append("Проверьте все эндпоинты в продакшене")
        elif category == "targeting":
            recs.append("⚠️ Проверьте все активные кампании")
            recs.append("Возможна потеря таргетинга")
        elif category == "placement":
            recs.append("⚠️ Пересмотрите стратегию размещения")
            recs.append("Переместите бюджет на активные плейсменты")
        elif category == "policy":
            recs.append("⚠️ Немедленно проверьте креативы на соответствие")
            recs.append("Риск блокировки аккаунта")
    
    elif "ВАЖНО" in priority:
        if category == "api":
            recs.append("Обновите код в ближайшие 2 недели")
            recs.append("Протестируйте на staging окружении")
        elif category == "targeting":
            recs.append("Попробуйте новые опции таргетинга")
            recs.append("A/B тест со старыми настройками")
        elif category == "reporting":
            recs.append("Обновите дашборды и отчёты")
            recs.append("Проверьте исторические данные")
    
    else:  # Инфо
        if removed:
            recs.append("Ознакомьтесь с документацией")
        if added:
            recs.append("Рассмотрите новые возможности")
    
    return recs[:3]  # Максимум 3 рекомендации


def group_changes_by_region(details: List[Dict]) -> Dict[str, List[Dict]]:
    """Группирует изменения по регионам для отправки в одном сообщении"""
    grouped = {}
    
    for detail in details:
        region = detail.get("region", "GLOBAL")
        
        # Если есть региональные различия - добавляем в соответствующий регион
        if region not in grouped:
            grouped[region] = []
        grouped[region].append(detail)
    
    # Логируем группировку для отладки
    log.info(f"📊 Группировка по регионам: {', '.join([f'{k}({len(v)})' for k, v in grouped.items()])}")
    
    return grouped

def format_region_summary(region: str, details: List[Dict]) -> List[str]:
    """Форматирует сводку изменений для региона"""
    if not details:
        return []
    
    region_badge = REGION_BADGES.get(region, f"🌍 [{region}]")
    output = []
    
    # Заголовок региона
    if region == "MD":
        output.append(f"🇲🇩 <b>МОЛДОВА ({region})</b>")
        output.append(f"📍 Обновления для молдавского региона")
    elif region == "EU":
        output.append(f"🇪🇺 <b>ЕВРОПА ({region})</b>")
        output.append(f"📍 Обновления для европейского региона")
    else:
        output.append(f"{region_badge} <b>ГЛОБАЛЬНЫЕ ИЗМЕНЕНИЯ</b>")
        output.append(f"📍 Обновления для всех регионов")
    
    output.append(f"━━━━━━━━━━━━━━━━━━━━━━")
    output.append("")
    
    # Форматируем каждое изменение в регионе
    for i, detail in enumerate(details, 1):
        title = detail.get("title", "")
        url = detail.get("url", "")
        
        gd = detail.get("global_diff") or {}
        changed = gd.get("changed") or []
        added = gd.get("added") or []
        removed = gd.get("removed") or []
        
        # Оценка приоритета
        priority_text, priority_icon = _assess_priority(
            " ".join([p.get("was", "") for p in changed]),
            " ".join([p.get("now", "") for p in changed]),
            added,
            removed
        )
        
        output.append(f"<b>{i}. {escape(title)}</b> {priority_icon}")
        
        # Краткое описание изменений
        changes_count = len(changed) + len(added) + len(removed)
        if changes_count > 0:
            change_parts = []
            if added:
                change_parts.append(f"+{len(added)}")
            if removed:
                change_parts.append(f"-{len(removed)}")
            if changed:
                change_parts.append(f"~{len(changed)}")
            
            output.append(f"📊 Изменения: {' '.join(change_parts)}")
        
        # Ключевые изменения (максимум 2 для краткости)
        key_changes = []
        for pair in changed[:2]:  # Только первые 2
            was = pair.get("was", "")
            now = pair.get("now", "")
            extracted = _extract_key_changes(was, now)
            key_changes.extend(extracted[:1])  # По 1 от каждого
        
        if key_changes:
            for change in key_changes[:2]:
                output.append(f"• {escape(change[:100])}{'...' if len(change) > 100 else ''}")
        
        if url:
            output.append(f"🔗 <a href='{escape(url)}'>Подробнее</a>")
        
        if i < len(details):  # Разделитель между изменениями
            output.append("")
    
    return ["\n".join(output)]

def format_change_smart(detail: Dict) -> List[str]:
    """
    Главная функция: форматирует изменение с анализом для таргетолога
    Возвращает список блоков текста для отправки
    """
    try:
        title = detail.get("title", "")
        url = detail.get("url", "")
        
        # Определяем тип источника
        is_api = "api" in url.lower() or "developers.facebook.com" in url
        is_policy = "transparency.meta.com" in url or "policy" in url.lower()
        
        if is_api:
            formatted = _format_api_change(detail)
        elif is_policy:
            formatted = _format_policy_change(detail)
        else:
            # Общее форматирование
            formatted = _format_api_change(detail)  # используем тот же формат
        
        # Разбиваем на блоки по 3500 символов
        MAX_LEN = 3500
        blocks = []
        if len(formatted) <= MAX_LEN:
            blocks.append(formatted)
        else:
            # Простое разбиение по абзацам
            lines = formatted.split("\n")
            current_block = ""
            for line in lines:
                if len(current_block) + len(line) + 1 > MAX_LEN:
                    if current_block:
                        blocks.append(current_block)
                    current_block = line
                else:
                    current_block += ("\n" if current_block else "") + line
            if current_block:
                blocks.append(current_block)
        
        return blocks
    
    except Exception as e:
        log.error(f"Ошибка форматирования изменения: {e}", exc_info=True)
        # Fallback к простому форматированию
        title = detail.get("title", "")
        url = detail.get("url", "")
        return [f"• <b>{escape(title)}</b>\n\n⚠️ Обнаружены изменения\n\n🔗 {escape(url)}"]
