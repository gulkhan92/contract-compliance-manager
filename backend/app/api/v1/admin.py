from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import DbSession, require_role
from app.db.enums import UserRole
from app.db.models import User
from app.schemas.llm_usage import LLMUsageSummary
from app.services.alerts import run_alert_scan
from app.services.ingestion import retry_queued_extractions
from app.services.llm import quota

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/ping")
async def ping(
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN))],
) -> dict[str, str]:
    return {"status": "ok", "org_id": str(current_user.org_id)}


@router.get("/llm-usage", response_model=list[LLMUsageSummary])
async def get_llm_usage(
    db: DbSession,
    _current_user: Annotated[User, Depends(require_role(UserRole.ADMIN))],
) -> list[quota.ProviderUsageSummary]:
    return await quota.get_usage_summary(db)


@router.post("/extraction/retry")
async def trigger_extraction_retry(
    db: DbSession,
    _current_user: Annotated[User, Depends(require_role(UserRole.ADMIN))],
) -> dict[str, int]:
    result = await retry_queued_extractions(db)
    await db.commit()
    return {
        "jobs_retried": result.jobs_retried,
        "jobs_succeeded": result.jobs_succeeded,
        "jobs_still_queued": result.jobs_still_queued,
    }


@router.post("/alerts/scan")
async def trigger_alert_scan(
    db: DbSession,
    _current_user: Annotated[User, Depends(require_role(UserRole.ADMIN))],
) -> dict[str, int]:
    result = await run_alert_scan(db)
    await db.commit()
    return {
        "statuses_recomputed": result.statuses_recomputed,
        "alerts_sent": result.alerts_sent,
        "alerts_failed": result.alerts_failed,
        "alerts_skipped_duplicate": result.alerts_skipped_duplicate,
    }

