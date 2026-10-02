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

    interview_postgres_user: str
    interview_postgres_password: SecretStr
    interview_postgres_db: str
    interview_postgres_host: str = "127.0.0.1"
    interview_postgres_port: int = 5435
    auth_jwt_secret: SecretStr = Field(min_length=32)
    internal_service_secret: SecretStr = Field(min_length=32)

    @property
    def database_url(self) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=self.interview_postgres_user,
            password=self.interview_postgres_password.get_secret_value(),
            host=self.interview_postgres_host,
            port=self.interview_postgres_port,
            database=self.interview_postgres_db,
        )


settings = Settings()
