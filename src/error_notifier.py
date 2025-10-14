# -*- coding: utf-8 -*-
"""
Умная система уведомлений об ошибках для разработчика.
Отправляет только важные ошибки, фильтрует шум.
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
import asyncio

log = logging.getLogger(__name__)

# Кэш отправленных ошибок (чтобы не спамить одинаковыми)
_error_cache: Dict[str, datetime] = {}
_ERROR_COOLDOWN = timedelta(hours=1)  # Не отправлять одну ошибку чаще раза в час

# Уровни важности ошибок
ERROR_LEVELS = {
    "critical": "🔴",  # Критичные - отправляем всегда
    "high": "🟠",      # Важные - отправляем с фильтрацией
    "medium": "🟡",    # Средние - отправляем раз в час
    "low": "🟢",       # Низкие - только в сводке
}


def _should_notify(error_key: str, level: str) -> bool:
    """Проверяет, нужно ли отправлять уведомление об ошибке"""
    if level == "critical":
        return True  # Критичные всегда
    
    if level == "low":
        return False  # Низкие не отправляем
    
    # Проверяем кэш
    if error_key in _error_cache:
        last_sent = _error_cache[error_key]
        if datetime.now() - last_sent < _ERROR_COOLDOWN:
            return False  # Недавно уже отправляли
    
    # Обновляем кэш
    _error_cache[error_key] = datetime.now()
    return True


def _classify_error(error_type: str, message: str) -> str:
    """Определяет уровень важности ошибки"""
    message_lower = message.lower()
    
    # Критичные ошибки
    if any(word in message_lower for word in [
        "bot token", "authentication", "unauthorized", 
        "credential", "permission denied", "access denied"
    ]):
        return "critical"
    
    # Важные ошибки
    if any(word in message_lower for word in [
        "timeout", "connection", "network", "database",
        "fatal", "crash", "exception"
    ]):
        return "high"
    
    # Средние (известные проблемы)
    if any(word in message_lower for word in [
        "502", "503", "429", "temporarily blocked",
        "rate limit", "too many requests"
    ]):
        return "medium"
    
    # Низкие (ожидаемые)
    if any(word in message_lower for word in [
        "chat not found", "user blocked", "403 forbidden",
        "no_peer"
    ]):
        return "low"
    
    # По умолчанию - важные
    return "high"


def _format_error_message(error_type: str, message: str, level: str, context: Optional[Dict] = None) -> str:
    """Форматирует сообщение об ошибке для Telegram"""
    icon = ERROR_LEVELS.get(level, "⚠️")
    
    lines = [
        f"{icon} <b>Ошибка в боте</b>",
        f"<b>Тип:</b> {error_type}",
        f"<b>Уровень:</b> {level.upper()}",
        "",
        f"<b>Сообщение:</b>",
        f"<code>{message[:500]}</code>",  # Ограничиваем длину
    ]
    
    if context:
        lines.append("")
        lines.append("<b>Контекст:</b>")
        for key, value in context.items():
            if value:
                lines.append(f"• {key}: <code>{str(value)[:100]}</code>")
    
    lines.append("")
    lines.append(f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    return "\n".join(lines)


async def notify_error(
    error_type: str,
    message: str,
    context: Optional[Dict] = None,
    force: bool = False
):
    """
    Отправляет уведомление об ошибке разработчику.
    
    Параметры:
    - error_type: Тип ошибки (напр. "Parsing Error", "Network Error")
    - message: Описание ошибки
    - context: Дополнительный контекст (url, source и т.д.)
    - force: Отправить независимо от фильтров
    """
    try:
        # Классифицируем ошибку
        level = _classify_error(error_type, message)
        
        # Создаём уникальный ключ для кэша
        error_key = f"{error_type}:{message[:100]}"
        
        # Проверяем, нужно ли отправлять
        if not force and not _should_notify(error_key, level):
            log.debug(f"Пропускаем уведомление об ошибке: {error_key} (недавно отправляли)")
            return
        
        # Форматируем сообщение
        formatted = _format_error_message(error_type, message, level, context)
        
        # Отправляем через telegram_notify
        from .telegram_notify import notify_dev
        await notify_dev(formatted)
        
        log.info(f"Отправлено уведомление об ошибке разработчику: {error_type}")
    
    except Exception as e:
        log.error(f"Не удалось отправить уведомление об ошибке: {e}")


async def notify_errors_summary(errors: list):
    """
    Отправляет сводку по ошибкам после завершения парсинга.
    
    Параметры:
    - errors: Список ошибок из run_update()
    """
    if not errors:
        return
    
    try:
        # Группируем ошибки по типу
        error_groups = {}
        for err in errors:
            error_type = err.get("error", "Unknown")
            if error_type not in error_groups:
                error_groups[error_type] = []
            error_groups[error_type].append(err)
        
        # Формируем сводку
        lines = [
            "📊 <b>Сводка по ошибкам</b>",
            "",
            f"Всего ошибок: {len(errors)}",
            f"Типов ошибок: {len(error_groups)}",
            "",
        ]
        
        # Топ-3 типа ошибок
        sorted_groups = sorted(error_groups.items(), key=lambda x: len(x[1]), reverse=True)
        for i, (error_type, error_list) in enumerate(sorted_groups[:3], 1):
            count = len(error_list)
            sources = [e.get("tag", "?") for e in error_list[:3]]
            
            lines.append(f"{i}. <b>{error_type[:50]}</b>")
            lines.append(f"   Количество: {count}")
            lines.append(f"   Источники: {', '.join(sources)}")
            if count > 3:
                lines.append(f"   <i>... и ещё {count - 3}</i>")
            lines.append("")
        
        if len(sorted_groups) > 3:
            lines.append(f"<i>... и ещё {len(sorted_groups) - 3} типов ошибок</i>")
        
        lines.append("")
        lines.append("💡 <i>Используйте /refresh для повторной попытки</i>")
        
        message = "\n".join(lines)
        
        # Отправляем только если много ошибок (> 30% источников)
        from .config import SOURCES
        error_rate = len(errors) / len(SOURCES) if SOURCES else 0
        
        if error_rate > 0.3:  # Больше 30% источников с ошибками
            from .telegram_notify import notify_dev
            await notify_dev(message)
            log.info(f"Отправлена сводка по ошибкам: {len(errors)} ошибок")
    
    except Exception as e:
        log.error(f"Не удалось отправить сводку по ошибкам: {e}")


# Удобные алиасы для разных типов ошибок
async def notify_parsing_error(url: str, error: str):
    """Уведомление об ошибке парсинга"""
    await notify_error(
        "Parsing Error",
        error,
        context={"URL": url}
    )


async def notify_network_error(url: str, error: str):
    """Уведомление об ошибке сети"""
    await notify_error(
        "Network Error",
        error,
        context={"URL": url}
    )


async def notify_proxy_error(error: str):
    """Уведомление об ошибке прокси"""
    await notify_error(
        "Proxy Error",
        error,
        force=True  # Ошибки прокси важны
    )


async def notify_telegram_error(error: str):
    """Уведомление об ошибке Telegram"""
    await notify_error(
        "Telegram Error",
        error
    )


async def notify_critical(error: str, context: Optional[Dict] = None):
    """Критичное уведомление (всегда отправляется)"""
    await notify_error(
        "Critical Error",
        error,
        context=context,
        force=True
    )
