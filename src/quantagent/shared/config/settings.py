"""Pydantic Settings for runtime configuration."""

from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Load connection settings from environment / `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    postgres_user: str = Field(default="quantagent", alias="POSTGRES_USER")
    postgres_db: str = Field(default="quantagent", alias="POSTGRES_DB")
    postgres_host: str = Field(default="127.0.0.1", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    pg_password: str = Field(default="change-me", alias="PG_PASSWORD")
    database_url_override: str | None = Field(default=None, alias="DATABASE_URL")

    data_raw_dir: Path = Field(default=Path("data/raw"), alias="DATA_RAW_DIR")
    akshare_rate_limit: float = Field(default=0.5, alias="AKSHARE_RATE_LIMIT")
    baostock_rate_limit: float = Field(default=0.2, alias="BAOSTOCK_RATE_LIMIT")
    # Windows often points HTTP(S) at a local Clash port; if that client is down,
    # akshare/baostock fail with ProxyError. Default: bypass system proxy for collectors.
    # NOTE: env name must NOT end with `_PROXY` — urllib treats `*_PROXY` as a proxy URL.
    collector_bypass_proxy: bool = Field(default=True, alias="COLLECTOR_DISABLE_SYSTEM_PROXY")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override
        user = quote_plus(self.postgres_user)
        password = quote_plus(self.pg_password)
        return (
            f"postgresql+psycopg://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
