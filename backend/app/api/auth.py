from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from kiteconnect.exceptions import KiteException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.kite import service

router = APIRouter(prefix="/auth/kite", tags=["auth"])


def _to_settings(**params: str) -> RedirectResponse:
    return RedirectResponse(f"{get_settings().frontend_url}/settings?{urlencode(params)}", status_code=303)


@router.get("/login")
def kite_login() -> RedirectResponse:
    url = service.login_url()
    if url is None:
        raise HTTPException(status_code=503, detail="Kite API key and secret are not configured")
    return RedirectResponse(url, status_code=307)


@router.get("/callback")
def kite_callback(
    request_token: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if status != "success" or not request_token:
        return _to_settings(kite="error", reason="Login was cancelled or failed at Zerodha")
    try:
        session = service.create_session(db, request_token)
    except (KiteException, service.KiteNotConfigured) as exc:
        return _to_settings(kite="error", reason=str(exc)[:200])
    return _to_settings(kite="connected", user=session.user_id)
