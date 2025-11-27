from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Proxy Auth
    PROXY_API_KEY: str

    # Upstream Configuration
    UPSTREAM_BASE_URL: str
    UPSTREAM_API_KEY: str | None = None

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./llm_proxier.db"
    AUTO_MIGRATE_DB: bool = True

    # Admin Dashboard
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "password"

    # CORS
    CORS_ALLOW_ORIGINS: list[str] = ["*"]

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
