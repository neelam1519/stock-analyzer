from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.orm import Session

from app.core.clock import is_market_hours, now_ist
from app.core.config import get_settings
from app.core.db import get_db

router = APIRouter(tags=["health"])
protected_router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "env": settings.app_env,
        "trading_mode": settings.trading_mode,
        "time_ist": now_ist().isoformat(),
        "market_open": is_market_hours(),
    }


@protected_router.get("/health/db")
def health_db(db: Session = Depends(get_db)) -> dict:
    try:
        version = db.execute(text("SELECT @@VERSION")).scalar_one()
    except (OperationalError, InterfaceError, DBAPIError) as exc:
        reason = str(exc.orig).split("]")[-1].strip() if exc.orig else "connection failed"
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"SQL Server: {reason}") from exc
    return {"status": "ok", "server": str(version).splitlines()[0]}
