from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.core.clock import IST
from app.core.db import get_db
from app.ingest.candles import DAILY, ingest_candles
from app.ingest.universe import sync_instruments
from app.kite import service
from app.main import create_app
from tests.fakes import FakeKite, instrument_rows
from tests.test_ingest import UNIVERSE

HEADERS = {"X-API-Key": "test-key"}


@pytest.fixture
def client(db, settings):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, follow_redirects=False)


class FakeKiteConnect:
    def __init__(self, api_key):
        self.api_key = api_key

    def login_url(self):
        return f"https://kite.zerodha.com/connect/login?v=3&api_key={self.api_key}"

    def generate_session(self, request_token, api_secret):
        assert api_secret == "kite-secret"
        return {
            "user_id": "QQS078",
            "access_token": f"token-for-{request_token}",
            "login_time": datetime(2026, 11, 5, 9, 0),
        }

    def set_access_token(self, token):
        self.token = token


def test_kite_login_flow_stores_encrypted_session(client, db, monkeypatch):
    monkeypatch.setattr(service, "KiteConnect", FakeKiteConnect)
    monkeypatch.setattr(service, "utc_now", lambda: datetime(2026, 11, 5, 4, 0))

    status = client.get("/api/kite/status", headers=HEADERS).json()
    assert status["configured"] and not status["connected"]
    assert "api_key=kite-key" in status["login_url"]

    response = client.get("/auth/kite/callback?request_token=abc&action=login&status=success")
    assert response.status_code == 303
    assert response.headers["location"] == "http://front.test/settings?kite=connected&user=QQS078"

    session = service.active_session(db)
    assert session.user_id == "QQS078"
    assert "token-for-abc" not in session.access_token_enc
    assert session.expires_at == datetime(2026, 11, 6, 0, 30)
    assert client.get("/api/kite/status", headers=HEADERS).json()["connected"]


def test_kite_callback_rejects_cancelled_login(client):
    response = client.get("/auth/kite/callback?status=cancelled")
    assert response.status_code == 303
    assert "kite=error" in response.headers["location"]


def test_ingest_requires_kite_session(client):
    response = client.post("/api/ingest/candles?interval=day", headers=HEADERS)
    assert response.status_code == 409


def test_market_endpoints_serve_stored_candles(client, db, monkeypatch):
    monkeypatch.setenv("DAILY_HISTORY_DAYS", "20")
    from app.core import config

    config.get_settings.cache_clear()
    kite = FakeKite(instrument_rows())
    sync_instruments(db, kite, UNIVERSE)
    ingest_candles(db, kite, DAILY, now=datetime(2026, 11, 5, 18, 0, tzinfo=IST))

    items = client.get("/api/instruments", headers=HEADERS).json()["items"]
    assert [i["symbol"] for i in items] == ["NIFTY 50", "RELIANCE"]
    assert items[1]["last_close"] == 100.0 and items[1]["change_pct"] == 0.0

    detail = client.get("/api/stocks/RELIANCE", headers=HEADERS).json()
    assert detail["candles"]["day"]["last"] == "2026-11-05"

    candles = client.get("/api/stocks/RELIANCE/candles?interval=day&limit=5", headers=HEADERS).json()["candles"]
    assert len(candles) == 5 and candles[-1]["time"] == "2026-11-05"
    assert client.get("/api/stocks/NOPE", headers=HEADERS).status_code == 404
