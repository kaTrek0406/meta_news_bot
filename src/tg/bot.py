# -*- coding: utf-8 -*-
import logging
import os
import asyncio
import datetime
from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

from telegram import BotCommand
from telegram.ext import Application, ApplicationBuilder

from .handlers import setup_handlers, _sanitize_telegram_html, _is_meaningful_change  # используем форматтер из handlers
from ..pipeline import run_update
from ..llm_client import translate_compact_html  # автоперевод/сжатие
from ..smart_formatter import format_change_smart  # умное форматирование
from ..config import LOGS_DIR

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# 1) .env
# ──────────────────────────────────────────────────────────────
def _load_env():
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    env_path = os.path.join(root_dir, ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
        log.info(f"✅ Загружен .env: {env_path}")
    else:
        log.warning("⚠️ Файл .env не найден, будут использованы системные переменные.")

# ──────────────────────────────────────────────────────────────
# 2) Логи
# ──────────────────────────────────────────────────────────────
def _setup_logging():
    level = os.getenv("LOGLEVEL", "INFO").upper()
    root = logging.getLogger()
    if not root.handlers:
        root.setLevel(level)
        ch = logging.StreamHandler()
        ch.setLevel(level)
        root.addHandler(ch)
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(LOGS_DIR / "telegram.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        fh.setLevel(level)
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")
        fh.setFormatter(fmt)
        logging.getLogger().addHandler(fh)
    except Exception as e:
        log.error("file logging init failed: %s", e)

def _tune_lib_loggers():
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)

# ──────────────────────────────────────────────────────────────
# 3) Утилиты рассылки
# ──────────────────────────────────────────────────────────────
def _parse_chat_ids() -> list[int]:
    """Парсит TELEGRAM_CHAT_ID как список (поддерживает , ; \n \t и лишние пробелы)."""
    raw = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not raw:
        return []
    # нормализуем разделители
    sep_normalized = raw.replace(";", ",").replace("\n", ",").replace("\t", ",")
    out: list[int] = []
    for part in sep_normalized.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except Exception:
            # молча игнорируем мусор
            pass
    # убираем дубли, сохраняем порядок
    uniq: list[int] = []
    seen = set()
    for cid in out:
        if cid not in seen:
            seen.add(cid)
            uniq.append(cid)
    return uniq

def _dev_id() -> int | None:
    # по твоей просьбе dev по умолчанию = 527824690
    raw = os.getenv("TELEGRAM_DEV_CHAT_ID", "527824690").strip()
    try:
        return int(raw)
    except Exception:
        return None

def _needs_translation(s: str, max_len: int) -> bool:
    import re
    en = len(re.findall(r"[A-Za-z]", s))
    total = max(1, len(s))
    return en / total > 0.15 or len(s) > max_len

# ──────────────────────────────────────────────────────────────
# 4) Ежедневная задача
# ──────────────────────────────────────────────────────────────
AUTO_TRANSLATE = os.getenv("AUTO_TRANSLATE_DIFFS", "1") == "1"
MAX_NOTIFY_CHARS = int(os.getenv("MAX_NOTIFY_CHARS", "1400"))

async def _send_html(application: Application, chat_id: int, text: str):
    try:
        await application.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        log.error("send_message failed: %s", e)

async def _daily_job(context):
    app: Application = context.application
    dev_only = os.getenv("DAILY_DEV_ONLY", "0") == "1"  # опционально: рассылать только dev
    recipients = [_dev_id()] if dev_only else _parse_chat_ids()
    recipients = [x for x in recipients if x]

    if not recipients:
        log.warning("Нет получателей для ежедневной рассылки (TELEGRAM_CHAT_ID / TELEGRAM_DEV_CHAT_ID).")
        return

    try:
        res = await run_update()
        details = res.get("details") or []
        errors = res.get("errors") or []
        
        # Отправляем сводку по ошибкам разработчику
        from ..error_notifier import notify_errors_summary
        await notify_errors_summary(errors)
        
        # Фильтруем только значимые изменения
        meaningful_details = [d for d in details if _is_meaningful_change(d)]
        
        if not meaningful_details:
            msg = f"🟢 Всего изменений: {len(details)}\nЗначимых для таргетинга: 0\n\n🟢 Все изменения незначительные (обновление дат, версий)."
            for cid in recipients:
                await _send_html(app, cid, msg)
            return

        for d in meaningful_details:
            # Используем умное форматирование
            parts = format_change_smart(d)
            for p in parts:
                out = p
                if AUTO_TRANSLATE and _needs_translation(out, MAX_NOTIFY_CHARS):
                    try:
                        out = translate_compact_html(out, target_lang="ru", max_len=MAX_NOTIFY_CHARS)
                    except Exception:
                        out = p
                out = _sanitize_telegram_html(out)
                for cid in recipients:
                    await _send_html(app, cid, out)
                    # Маленькая задержка между сообщениями
                    await asyncio.sleep(0.3)

    except Exception as e:
        log.error("daily job error: %s", e, exc_info=True)
        # тихий push только деву
        did = _dev_id()
        if did:
            await _send_html(app, did, f"⚠️ Ошибка ежедневной рассылки: <code>{str(e)[:800]}</code>")

def _schedule_daily(app: Application):
    time_str = os.getenv("DAILY_DISPATCH_TIME", "09:00")
    tz_name = os.getenv("TZ", "UTC")
    try:
        hh, mm = [int(x) for x in time_str.split(":", 1)]
    except Exception:
        hh, mm = 9, 0
    tz = ZoneInfo(tz_name)
    when = datetime.time(hour=hh, minute=mm, tzinfo=tz)
    app.job_queue.run_daily(_daily_job, time=when, name="daily_dispatch")

# ──────────────────────────────────────────────────────────────
# 5) Старт
# ──────────────────────────────────────────────────────────────
async def error_handler(update, context):
    """Обработчик ошибок - логируем и уведомляем разработчика."""
    from telegram.error import Conflict
    
    # Игнорируем конфликты (два бота запущены одновременно)
    if isinstance(context.error, Conflict):
        log.warning("⚠️ Конфликт ботов: запущено 2 экземпляра одновременно. Остановите один из них.")
        return
    
    log.error("Ошибка в боте: %s", context.error, exc_info=context.error)
    
    # Уведомляем разработчика о критических ошибках
    dev_id = _dev_id()
    if dev_id and context.application:
        try:
            error_msg = f"⚠️ <b>Ошибка в боте:</b>\n<code>{str(context.error)[:800]}</code>"
            await context.application.bot.send_message(
                chat_id=dev_id,
                text=error_msg,
                parse_mode="HTML"
            )
        except Exception as e:
            log.error("Не удалось отправить уведомление об ошибке: %s", e)

def run_bot():
    _load_env()
    _setup_logging()
    _tune_lib_loggers()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")

    app: Application = ApplicationBuilder().token(token).build()
    
    # Добавляем обработчик ошибок
    app.add_error_handler(error_handler)
    
    setup_handlers(app)

    commands = [
        BotCommand("start", "Показать категории"),
        BotCommand("refresh", "Обновить источники вручную"),
        BotCommand("status", "Показать статистику"),
        BotCommand("help", "Справка"),
        BotCommand("testdispatch", "Тест ежедневной рассылки (dev)"),
    ]

    async def _post_init(application: Application):
        await application.bot.set_my_commands(commands)

    app.post_init = _post_init
    _schedule_daily(app)

    log.info("Бот запущен. Ожидаю команды…")
    app.run_polling(allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    run_bot()
