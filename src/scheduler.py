# -*- coding: utf-8 -*-

import asyncio
import logging
import os
from datetime import time
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .pipeline import run_update
from .telegram_notify import notify

logging.basicConfig(level=os.getenv("LOGLEVEL", "INFO"))
log = logging.getLogger(__name__)

TZ_NAME = os.getenv("TZ", "Europe/Chisinau")
DAILY_DISPATCH_TIME = os.getenv("DAILY_DISPATCH_TIME", "09:00")  # HH:MM

def _parse_hm(s: str) -> tuple[int, int]:
    hh, mm = (s or "09:00").split(":")
    return int(hh), int(mm)

async def job():
    """Основная задача: запускает обновление и уведомляет"""
    log.info("Запуск плановой проверки источников…")
    try:
        res = await run_update()
        changed = res.get("changed", 0)
        total_sec = res.get("sections_total_changed", 0)
        details = res.get("details", [])

        if changed == 0:
            await notify("✅ Проверка завершена. Новых изменений не найдено.")
            return

        msg_lines = [
            f"🕘 Ежедневная проверка завершена",
            f"Изменено страниц: {changed}, секций: {total_sec}",
            ""
        ]
        for d in details[:5]:
            ttl = d.get("title") or d.get("url") or ""
            url = d.get("url", "")
            diff = d.get("diff", {})
            if diff.get("added"):
                msg_lines.append(f"➕ *Добавлено:* {', '.join(diff['added'][:2])}")
            if diff.get("modified"):
                msg_lines.append(f"✎ *Изменено:* {', '.join(diff['modified'][:2])}")
            if diff.get("removed"):
                msg_lines.append(f"➖ *Удалено:* {', '.join(diff['removed'][:2])}")
            msg_lines.append(f"🔗 {url}\n")

        if len(details) > 5:
            msg_lines.append(f"…и ещё {len(details) - 5} изменений.")

        await notify("\n".join(msg_lines))

    except Exception as e:
        log.exception("Ошибка при автообновлении: %s", e)
        await notify(f"⚠️ Ошибка при автообновлении:\n{e}")

def run_scheduler():
    """Запуск ежедневного планировщика"""
    tz = ZoneInfo(TZ_NAME)
    hh, mm = _parse_hm(DAILY_DISPATCH_TIME)
    sch = AsyncIOScheduler(timezone=tz)
    trigger = CronTrigger(hour=hh, minute=mm, timezone=tz)
    sch.add_job(job, trigger, id="daily_update", max_instances=1, coalesce=True)
    sch.start()
    log.info("Планировщик запущен: %02d:%02d %s каждый день", hh, mm, TZ_NAME)
    return sch

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    scheduler = run_scheduler()
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
