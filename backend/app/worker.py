"""The `worker` process from infra/docker-compose.yml: runs the daily
obligation-status-recompute + alert-scan job (docs/CONTRACT_CLM_BUILD_PLAN.md
§9, §12 Phase 7), plus a periodic sweep that retries any extraction_job left
QUEUED because no LLM provider had quota headroom at upload time — via
APScheduler's AsyncIOScheduler.

Uses the default in-memory job store rather than the plan's suggested
SQLAlchemyJobStore: this process schedules a small, fixed set of jobs,
re-registered identically every time the worker starts, so there is nothing
for a persistent job store to actually recover across restarts — adding a
second, synchronous-driver database connection (SQLAlchemyJobStore doesn't
support asyncpg) for that would be complexity with no real benefit at this
stage. Documented here as a deliberate deviation, not an oversight.
"""

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.services.alerts import run_alert_scan
from app.services.ingestion import retry_queued_extractions

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def scheduled_alert_scan() -> None:
    async with AsyncSessionLocal() as session:
        result = await run_alert_scan(session)
        await session.commit()
        logger.info("Alert scan complete: %s", result)


async def scheduled_extraction_retry() -> None:
    async with AsyncSessionLocal() as session:
        result = await retry_queued_extractions(session)
        await session.commit()
        if result.jobs_retried:
            logger.info("Extraction retry sweep complete: %s", result)


async def main() -> None:
    settings = get_settings()
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        scheduled_alert_scan,
        CronTrigger(hour=settings.alert_scan_hour_utc, minute=settings.alert_scan_minute_utc),
        id="daily_alert_scan",
        replace_existing=True,
    )
    scheduler.add_job(
        scheduled_extraction_retry,
        IntervalTrigger(minutes=settings.extraction_retry_interval_minutes),
        id="extraction_retry_sweep",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "Worker started; daily alert scan scheduled for %02d:%02d UTC, "
        "extraction retry sweep every %d minutes.",
        settings.alert_scan_hour_utc,
        settings.alert_scan_minute_utc,
        settings.extraction_retry_interval_minutes,
    )
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
