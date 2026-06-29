"""Service configuration (pydantic-settings).

Only the surface needed to boot today lives here; tunables from requirements §12
(thresholds, fps, top_k, adapter impl names) are added as features land.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ML_", env_file=".env", extra="ignore")

    service_name: str = "ml-service"
    log_level: str = "INFO"


settings = Settings()
