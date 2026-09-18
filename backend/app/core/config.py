from functools import lru_cache

from pydantic import AnyHttpUrl, Field, PostgresDsn, RedisDsn, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    database_url: PostgresDsn
    sync_database_url: PostgresDsn
    redis_url: RedisDsn
    session_token_secret: SecretStr
    demo_staff_pin: SecretStr
    demo_mobile_app_api_key: SecretStr
    demo_notification_mode: str = "log"
    notification_delivery_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    notification_poll_seconds: float = Field(default=0.5, gt=0, le=60)
    notification_max_attempts: int = Field(default=5, ge=1, le=20)
    public_client_url: AnyHttpUrl = "http://localhost:3000"
    rate_limit_window_seconds: int = Field(default=60, ge=10, le=3600)
    staff_login_rate_limit: int = Field(default=20, ge=5, le=1000)
    ticket_write_rate_limit: int = Field(default=60, ge=10, le=5000)
    integration_rate_limit: int = Field(default=120, ge=10, le=10000)

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip().rstrip("/") for origin in self.cors_origins.split(",") if origin.strip()]

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        session_secret = self.session_token_secret.get_secret_value()
        integration_key = self.demo_mobile_app_api_key.get_secret_value()
        if len(session_secret) < 32:
            raise ValueError("SESSION_TOKEN_SECRET must contain at least 32 characters")
        if len(integration_key) < 32:
            raise ValueError("DEMO_MOBILE_APP_API_KEY must contain at least 32 characters")
        if "*" in self.allowed_origins:
            raise ValueError("CORS_ORIGINS must list explicit trusted origins")
        if self.app_env.lower() in {"production", "staging"}:
            placeholders = ("replace-with", "change-me", "development")
            protected = (
                session_secret,
                integration_key,
                self.demo_staff_pin.get_secret_value(),
            )
            if any(marker in value.lower() for value in protected for marker in placeholders):
                raise ValueError("Replace demo credentials before staging or production startup")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
