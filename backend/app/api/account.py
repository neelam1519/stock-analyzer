from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.trading.summary import account_summary, clear_cache

router = APIRouter(tags=["account"])


@router.get("/account/summary")
def summary(refresh: bool = False, db: Session = Depends(get_db)) -> dict:
    if refresh:
        clear_cache()
    return account_summary(db)
