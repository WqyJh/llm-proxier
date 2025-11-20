from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Proxy Auth
    PROXY_API_KEY: str

    # Upstream Configuration
    UPSTREAM_BASE_URL: str
    UPSTREAM_API_KEY: Optional[str] = None

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./llm_proxy.db"

    # Admin Dashboard
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "password"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
