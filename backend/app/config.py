from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment / .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Branding
    app_name: str = "DineMate"
    restaurant_name: str = "DineMate Kitchen"

    # LLM (DeepSeek, served over the OpenAI-compatible API)
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 800
    llm_timeout_seconds: int = 240
    llm_disable_thinking: bool = True
    llm_max_retries: int = 2
    max_agent_turns: int = 6
    use_fake_llm: bool = False
    testing: bool = False
    local_postgres_url: str = ""
    local_mongodb_url: str = ""

    # Short term memory (conversation turns)
    postgres_url: str = "postgresql+asyncpg://dinemate:dinemate@localhost:5433/dinemate"

    # Long term memory (personal preferences / personal data)
    mongodb_url: str = "mongodb://localhost:27018"
    mongodb_db: str = "dinemate"

    # Auth
    jwt_secret: str = "dev-only-insecure-secret-change-me-in-production!"
    jwt_issuer: str = "dinemate"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_days: int = 30
    cookie_secure: bool = False
    cookie_domain: str = ""

    # Domain rules (DOMAIN_MODEL.md)
    # Currency. PKR has no practical subunit, so minor_units == rupees and
    # nothing is shown after a decimal point. Arithmetic stays integer either way.
    currency_symbol: str = "Rs "
    currency_decimals: int = 0
    tax_rate: float = 0.16
    cancellation_window_minutes: int = 10
    confirmation_token_ttl_seconds: int = 300
    history_turns: int = 12
    memory_confidence_floor: float = 0.8

    # API
    cors_origins: list[str] = ["http://localhost:3000"]
    environment: str = "development"
    internal_secret: str = "dev-internal-secret"

    @property
    def active_postgres_url(self) -> str:
        """Tests run against local Docker, never the shared Neon branch."""
        if self.testing and self.local_postgres_url:
            return self.local_postgres_url
        return self.postgres_url

    @property
    def active_mongodb_url(self) -> str:
        """Tests use the local Mongo, never the shared Atlas cluster."""
        if self.testing and self.local_mongodb_url:
            return self.local_mongodb_url
        return self.mongodb_url

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.is_production:
        if len(s.jwt_secret) < 32 or "dev-only" in s.jwt_secret:
            raise RuntimeError("JWT_SECRET must be set to a strong value in production")
    return s


settings = get_settings()
