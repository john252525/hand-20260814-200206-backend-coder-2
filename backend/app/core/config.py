from functools import lru_cache
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_env: str = "development"
    app_debug: bool = True
    app_secret_key: str = "change-me"

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "tender_pipeline"
    postgres_user: str = "tender_user"
    postgres_password: str = "change-me"

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.postgres_user}:{quote_plus(self.postgres_password)}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # LLM
    llm_api_key: str = ""
    llm_api_base: str = "https://api.openai.com/v1"
    llm_model_chat: str = "gpt-4o-mini"
    llm_model_embedding: str = "text-embedding-3-small"
    llm_embedding_dimensions: int = 1536

    # Google Search
    google_search_api_key: str = ""
    google_search_cx: str = ""
    google_search_max_results: int = 10

    # Email
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True

    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    imap_use_ssl: bool = True

    # Files
    upload_dir: str = "/app/uploads"

    # Telegram
    telegram_bot_token: str = ""

    # S3/MinIO
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "tender-files"
    s3_use_ssl: bool = False

    # Encryption
    encryption_key: str = ""

    # Tender source (ГосПлан)
    tender_source_api_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
