from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "dev"
    backend_api_key: str = "change-me"
    cors_origins: list[str] = ["http://localhost:3100"]
    frontend_url: str = "http://localhost:3100"

    mssql_host: str = "localhost"
    mssql_port: int = 1433
    mssql_database: str = "stocks"
    mssql_user: str = "sa"
    mssql_password: str = ""
    mssql_driver: str = "ODBC Driver 18 for SQL Server"
    mssql_encrypt: bool = True
    mssql_trust_server_certificate: bool = True

    kite_api_key: str = ""
    kite_api_secret: str = ""
    kite_redirect_url: str = "http://127.0.0.1:8100/auth/kite/callback"
    kite_min_request_interval: float = 0.35
    daily_history_days: int = 1825
    intraday_history_days: int = 365

    token_encryption_key: str = ""

    llm_model: str = "gemini/gemini-3.5-flash-lite"
    llm_batch_size: int = 8
    llm_max_articles_per_run: int = 160
    llm_timeout_seconds: int = 90
    gemini_api_key: str = ""
    xai_api_key: str = ""
    openai_api_key: str = ""
    groq_api_key: str = ""
    deepseek_api_key: str = ""
    openrouter_api_key: str = ""
    news_lookback_days: int = 3
    scheduler_enabled: bool = True
    research_top_n: int = 10
    trading_mode: str = "paper"

    @property
    def llm_provider(self) -> str:
        return self.llm_model.split("/", 1)[0] if "/" in self.llm_model else "openai"

    @property
    def llm_api_key(self) -> str:
        return getattr(self, f"{self.llm_provider}_api_key", "")

    @property
    def database_url(self) -> URL:
        return URL.create(
            "mssql+pyodbc",
            username=self.mssql_user,
            password=self.mssql_password,
            host=self.mssql_host,
            port=self.mssql_port,
            database=self.mssql_database,
            query={
                "driver": self.mssql_driver,
                "Encrypt": "yes" if self.mssql_encrypt else "no",
                "TrustServerCertificate": "yes" if self.mssql_trust_server_certificate else "no",
            },
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
