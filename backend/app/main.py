from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.services.embeddings import get_embedding_model


async def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please try again later."},
    )


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    # Load the embedding model once, at process startup, rather than
    # paying that cost on whichever request happens to need it first — see
    # docs/CONTRACT_CLM_BUILD_PLAN.md §4/§12 Phase 4. get_embedding_model()
    # is itself cached, so this is what makes "loaded once" actually true.
    get_embedding_model()
    yield


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=_lifespan,
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    app.add_middleware(SlowAPIMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.api_v1_prefix)

    return app


app = create_app()
