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


def test_llm_key_works_for_any_provider(settings, monkeypatch):
    from app.core import config

    def fresh(**env):
        for key in ("LLM_API_KEY", "GITHUB_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        config.get_settings.cache_clear()
        return config.get_settings()

    assert fresh(LLM_MODEL="github/gpt-4o-mini", GITHUB_API_KEY="gh").llm_api_key == "gh"
    assert fresh(LLM_MODEL="anthropic/claude-sonnet-5-5", ANTHROPIC_API_KEY="an").llm_api_key == "an"
    assert fresh(LLM_MODEL="gemini/x", GEMINI_API_KEY="ge").llm_api_key == "ge"
    assert fresh(LLM_MODEL="github/gpt-4o-mini", GITHUB_API_KEY="gh", LLM_API_KEY="any").llm_api_key == "any"
    assert fresh(LLM_MODEL="github/gpt-4o-mini").llm_api_key == ""
