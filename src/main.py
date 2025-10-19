# -*- coding: utf-8 -*-
import asyncio, logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from .pipeline import run_update

logging.basicConfig(level=logging.INFO)

async def job():
    await run_update()

def run_scheduler():
    sch = AsyncIOScheduler(timezone="UTC")
    sch.add_job(job, "interval", hours=24, id="periodic_update", max_instances=1, coalesce=True)
    sch.start()
    return sch

# Force Railway restart - 2025-10-19 00:10 UTC
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    scheduler = run_scheduler()
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
