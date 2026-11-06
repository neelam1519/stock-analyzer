from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import config
from app.models import SCHEMAS, Base


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("BACKEND_API_KEY", "test-key")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("MSSQL_HOST", "db.local")
    monkeypatch.setenv("MSSQL_PASSWORD", "p@ss;word")
    monkeypatch.setenv("KITE_API_KEY", "kite-key")
    monkeypatch.setenv("KITE_API_SECRET", "kite-secret")
    monkeypatch.setenv("FRONTEND_URL", "http://front.test")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    config.get_settings.cache_clear()
    yield config.get_settings()
    config.get_settings.cache_clear()


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _setup(dbapi_connection, _):
        dbapi_connection.create_function(
            "sysutcdatetime", 0, lambda: datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")
        )
        for schema in SCHEMAS:
            dbapi_connection.execute(f"ATTACH DATABASE ':memory:' AS {schema}")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()
