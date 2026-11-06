from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.kite import service

router = APIRouter(prefix="/kite", tags=["kite"])


@router.get("/status")
def kite_status(db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    session = service.active_session(db)
    return {
        "configured": bool(settings.kite_api_key and settings.kite_api_secret),
        "connected": session is not None,
        "user_id": session.user_id if session else None,
        "expires_at": session.expires_at.isoformat() + "Z" if session else None,
        "login_url": service.login_url(),
    }
