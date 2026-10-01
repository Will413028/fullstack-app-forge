from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FORGE_", extra="ignore")

    database_url: str = Field(default="postgresql://postgres@127.0.0.1:5432/forge", repr=False)
    platform_origin: str = "http://localhost:3000"
    secure_cookies: bool = False
    session_hours: int = Field(default=8, ge=1, le=24)
    data_path: Path = Path(__file__).resolve().parents[2] / ".forge"
    max_run_seconds: int = Field(default=900, ge=1, le=1800)
    lease_seconds: int = Field(default=30, ge=10, le=120)
    max_attempts: int = Field(default=2, ge=1, le=3)
    max_active_runs: int = Field(default=1, ge=1, le=2)
    model_base_url: str | None = None
    model_name: str | None = None
    model_api_key: str | None = Field(default=None, repr=False)
    max_model_tokens: int = Field(default=16000, ge=512, le=64000)


settings = Settings()
