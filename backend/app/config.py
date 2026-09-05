from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment / .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM (DeepSeek, served over the OpenAI-compatible API)
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"

    # Short term memory (conversation turns)
    postgres_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/restaurant"

    # Long term memory (personal preferences / personal data)
    mongodb_url: str = "mongodb://localhost:27017"
    mongodb_db: str = "restaurant_agent"

    # API
    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
