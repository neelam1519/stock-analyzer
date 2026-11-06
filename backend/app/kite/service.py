import time as systime
from datetime import date, datetime
from threading import Lock
from typing import Any, Protocol

from kiteconnect import KiteConnect
from kiteconnect.exceptions import TokenException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import kite_token_expiry, now_ist, to_utc_naive, utc_now
from app.core.config import get_settings
from app.core.security import decrypt, encrypt
from app.models import KiteSession


class KiteNotConfigured(RuntimeError):
    pass


class KiteNotConnected(RuntimeError):
    pass


class MarketDataClient(Protocol):
    def instruments(self, exchange: str | None = None) -> list[dict[str, Any]]: ...

    def historical_data(
        self, instrument_token: int, from_date: date | datetime, to_date: date | datetime, interval: str
    ) -> list[dict[str, Any]]: ...

    def ltp(self, instruments: list[str]) -> dict[str, dict[str, Any]]: ...


class Throttle:
    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._last = 0.0
        self._lock = Lock()

    def wait(self) -> None:
        with self._lock:
            delay = self._last + self.min_interval - systime.monotonic()
            if delay > 0:
                systime.sleep(delay)
            self._last = systime.monotonic()


_throttle = Throttle(get_settings().kite_min_request_interval)


class ThrottledKite:
    def __init__(self, kite: KiteConnect, db: Session, session: KiteSession):
        self._kite = kite
        self._db = db
        self._session = session

    def _call(self, fn, *args, **kwargs):
        _throttle.wait()
        try:
            return fn(*args, **kwargs)
        except TokenException as exc:
            self._session.expires_at = utc_now()
            self._db.add(self._session)
            self._db.commit()
            raise KiteNotConnected("Kite session expired, log in again") from exc

    def instruments(self, exchange: str | None = None) -> list[dict[str, Any]]:
        return self._call(self._kite.instruments, exchange)

    def historical_data(self, instrument_token, from_date, to_date, interval):
        return self._call(self._kite.historical_data, instrument_token, from_date, to_date, interval)

    def ltp(self, instruments: list[str]) -> dict[str, dict[str, Any]]:
        quotes: dict[str, dict[str, Any]] = {}
        for start in range(0, len(instruments), 500):
            quotes.update(self._call(self._kite.ltp, instruments[start : start + 500]))
        return quotes

    def place_order(self, **payload) -> str:
        return self._call(self._kite.place_order, **payload)

    def cancel_order(self, variety: str, order_id: str):
        return self._call(self._kite.cancel_order, variety, order_id)

    def orders(self) -> list[dict[str, Any]]:
        return self._call(self._kite.orders)

    def margins(self, segment: str = "equity") -> dict[str, Any]:
        return self._call(self._kite.margins, segment)

    def holdings(self) -> list[dict[str, Any]]:
        return self._call(self._kite.holdings)

    def positions(self) -> dict[str, list[dict[str, Any]]]:
        return self._call(self._kite.positions)

    def place_gtt(self, **payload) -> dict[str, Any]:
        return self._call(self._kite.place_gtt, **payload)

    def modify_gtt(self, trigger_id: int, **payload) -> dict[str, Any]:
        return self._call(self._kite.modify_gtt, trigger_id, **payload)

    def get_gtt(self, trigger_id: int) -> dict[str, Any]:
        return self._call(self._kite.get_gtt, trigger_id)

    def delete_gtt(self, trigger_id: int) -> dict[str, Any]:
        return self._call(self._kite.delete_gtt, trigger_id)


def _base_client() -> KiteConnect:
    settings = get_settings()
    if not settings.kite_api_key or not settings.kite_api_secret:
        raise KiteNotConfigured("KITE_API_KEY and KITE_API_SECRET must be set in .env")
    return KiteConnect(api_key=settings.kite_api_key)


def login_url() -> str | None:
    try:
        return _base_client().login_url()
    except KiteNotConfigured:
        return None


def create_session(db: Session, request_token: str) -> KiteSession:
    kite = _base_client()
    data = kite.generate_session(request_token, api_secret=get_settings().kite_api_secret)
    login_time = data.get("login_time")
    if not isinstance(login_time, datetime):
        login_time = now_ist()
    session = KiteSession(
        user_id=data["user_id"],
        access_token_enc=encrypt(data["access_token"]),
        login_time=to_utc_naive(login_time),
        expires_at=kite_token_expiry(login_time),
    )
    db.add(session)
    db.commit()
    return session


def active_session(db: Session) -> KiteSession | None:
    return db.scalar(
        select(KiteSession)
        .where(KiteSession.expires_at > utc_now())
        .order_by(KiteSession.login_time.desc(), KiteSession.id.desc())
    )


def market_client(db: Session) -> MarketDataClient:
    session = active_session(db)
    if session is None:
        raise KiteNotConnected("No active Kite session, log in from Settings")
    kite = _base_client()
    kite.set_access_token(decrypt(session.access_token_enc))
    return ThrottledKite(kite, db, session)
