"""Top-level aggregator for all /api/v1 routers.

Feature routers (obligations, alerts, dashboard, precedents) are registered
here as they are implemented in later phases.
"""

from fastapi import APIRouter

from app.api.v1.admin import router as admin_router
from app.api.v1.alerts import router as alerts_router
from app.api.v1.audit import router as audit_router
from app.api.v1.auth import router as auth_router
from app.api.v1.chat import router as chat_router
from app.api.v1.contracts import router as contracts_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.health import router as health_router
from app.api.v1.obligations import router as obligations_router
from app.api.v1.precedents import router as precedents_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(auth_router)
api_router.include_router(admin_router)
api_router.include_router(contracts_router)
api_router.include_router(obligations_router)
api_router.include_router(alerts_router)
api_router.include_router(audit_router)
api_router.include_router(dashboard_router)
api_router.include_router(precedents_router)
api_router.include_router(chat_router)

