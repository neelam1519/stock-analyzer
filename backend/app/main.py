import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import account, auth, backtests, health, ingest, kite, live, market, news, portfolio, signals
from app.core.config import get_settings
from app.core.security import require_api_key


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if get_settings().scheduler_enabled:
        from app.core.calendar import refresh_holidays
        from app.core.db import get_sessionmaker
        from app.scheduler import runner

        with get_sessionmaker()() as db:
            refresh_holidays(db)
        runner.start()
    yield
    if get_settings().scheduler_enabled:
        from app.scheduler import runner

        runner.shutdown()


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO)
    app = FastAPI(title="Stock Analyzer API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(auth.router)
    protected = [Depends(require_api_key)]
    for router in (
        health.protected_router,
        kite.router,
        market.router,
        ingest.router,
        news.router,
        signals.router,
        backtests.router,
        portfolio.router,
        live.router,
        account.router,
    ):
        app.include_router(router, prefix="/api", dependencies=protected)
    return app


app = create_app()
