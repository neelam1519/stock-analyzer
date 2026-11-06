from datetime import datetime

from fastapi.testclient import TestClient

from app.core import security
from app.core.clock import IST, is_market_hours
from app.main import create_app
from app.models import SCHEMAS, Base


def test_database_url_targets_mssql_with_odbc18(settings):
    url = settings.database_url
    assert url.drivername == "mssql+pyodbc"
    assert url.host == "db.local"
    assert url.password == "p@ss;word"
    assert url.query["driver"] == "ODBC Driver 18 for SQL Server"
    assert url.query["TrustServerCertificate"] == "yes"


def test_token_encryption_roundtrip(settings):
    token = "kite-access-token-123"
    encrypted = security.encrypt(token)
    assert encrypted != token
    assert security.decrypt(encrypted) == token


def test_market_hours_ist():
    assert is_market_hours(datetime(2026, 11, 5, 10, 0, tzinfo=IST))
    assert not is_market_hours(datetime(2026, 11, 5, 16, 0, tzinfo=IST))
    assert not is_market_hours(datetime(2026, 11, 7, 10, 0, tzinfo=IST))


def test_models_cover_all_schemas():
    schemas = {table.schema for table in Base.metadata.tables.values()}
    assert schemas == set(SCHEMAS)
    assert "mkt.daily_candles" in Base.metadata.tables
    assert "app.kite_sessions" in Base.metadata.tables


def test_health_public_and_api_requires_key(settings):
    client = TestClient(create_app())
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/api/health/db").status_code == 401
    assert client.get("/api/health/db", headers={"X-API-Key": "wrong"}).status_code == 401


def test_db_health_reports_503_when_unreachable(settings, monkeypatch):
    from sqlalchemy.exc import OperationalError

    from app.core.db import get_db

    class BrokenSession:
        def execute(self, *args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception("[08001] Login timeout expired"))

    app = create_app()
    app.dependency_overrides[get_db] = lambda: BrokenSession()
    response = TestClient(app).get("/api/health/db", headers={"X-API-Key": "test-key"})
    assert response.status_code == 503
    assert "Login timeout expired" in response.json()["detail"]
