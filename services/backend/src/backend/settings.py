"""Backend configuration (pydantic-settings)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BE_", env_file=".env", extra="ignore")

    service_name: str = "backend"
    log_level: str = "INFO"
    # URL the backend uses to reach the ML service (set per environment).
    ml_service_url: str = "http://ml-service:8000"


settings = Settings()
