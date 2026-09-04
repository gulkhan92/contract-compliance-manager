"""Top-level aggregator for all /api/v1 routers.

Feature routers (auth, contracts, obligations, alerts, dashboard,
precedents, admin) are registered here as they are implemented in later
phases.
"""

from fastapi import APIRouter

from app.api.v1.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
