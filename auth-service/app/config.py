from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        extra="ignore",
        hide_input_in_errors=True,
    )

    redis_url: SecretStr
    auth_login_rate_limit: int = Field(default=5, ge=1)
    auth_register_rate_limit: int = Field(default=5, ge=1)
    auth_rate_limit_window_seconds: int = Field(default=60, ge=1)
    auth_rate_limit_prefix: str = Field(default="hireflow:rate-limit", min_length=1)

    auth_postgres_user: str
    auth_postgres_password: SecretStr
    auth_postgres_db: str
    auth_postgres_host: str = "127.0.0.1"
    auth_postgres_port: int = 5433
    auth_jwt_secret: SecretStr = Field(min_length=32)
    recruiter_creation_secret: SecretStr = Field(min_length=32)
    auth_access_token_expire_minutes: int = Field(default=30, ge=1)

    @property
    def database_url(self) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=self.auth_postgres_user,
            password=self.auth_postgres_password.get_secret_value(),
            host=self.auth_postgres_host,
            port=self.auth_postgres_port,
            database=self.auth_postgres_db,
        )


settings = Settings()
