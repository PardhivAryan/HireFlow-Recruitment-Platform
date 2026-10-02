from pathlib import Path

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        extra="ignore",
        hide_input_in_errors=True,
    )

    recruitment_postgres_user: str
    recruitment_postgres_password: SecretStr
    recruitment_postgres_db: str
    recruitment_postgres_host: str = "127.0.0.1"
    recruitment_postgres_port: int = 5434
    auth_jwt_secret: SecretStr = Field(min_length=32)
    interview_service_url: AnyHttpUrl
    internal_service_secret: SecretStr = Field(min_length=32)

    @property
    def database_url(self) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=self.recruitment_postgres_user,
            password=self.recruitment_postgres_password.get_secret_value(),
            host=self.recruitment_postgres_host,
            port=self.recruitment_postgres_port,
            database=self.recruitment_postgres_db,
        )


settings = Settings()
