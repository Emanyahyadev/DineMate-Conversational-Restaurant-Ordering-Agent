from functools import lru_cache
from typing import Literal

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
    # Each tool call costs a turn. "One chicken karahi and a garlic naan" is a
    # search and an add per dish plus the read-back, which is already 5 - at 6
    # a perfectly ordinary two-dish order ran out mid-way and reported failure
    # while the cart had in fact been filled.
    max_agent_turns: int = 12
    use_fake_llm: bool = False
    testing: bool = False
    local_postgres_url: str = ""
    local_mongodb_url: str = ""

    # Short term memory (conversation turns)
    postgres_url: str = "postgresql+asyncpg://dinemate:dinemate@localhost:5433/dinemate"

    # Long term memory (personal preferences / personal data)
    mongodb_url: str = "mongodb://localhost:27018"
    mongodb_db: str = "dinemate"
    mongo_max_pool_size: int = 10

    # Postgres pool, per worker. The ceiling that matters is Neon's connection
    # limit divided by the number of workers, so this is configurable rather
    # than assumed: 5 + 10 per worker suits a couple of container instances,
    # and wants lowering again if the worker count goes up.
    pg_pool_size: int = 5
    pg_max_overflow: int = 10

    # Check a pooled connection is still alive before handing it out. On by
    # default because Neon suspends an idle compute and its PgBouncer recycles
    # server connections, and a dead connection surfaces as a failed request
    # rather than a slow one.
    #
    # It is not free: the check is a round trip, so it costs whatever one round
    # trip to the database costs - measured at ~0.9 s per request against a
    # Neon branch in another region, which is about 40% of every request. Turn
    # it off when the database is close (a local Postgres, or the same region),
    # where the check buys much less than it costs.
    pg_pool_pre_ping: bool = True

    # Auth
    jwt_secret: str = "dev-only-insecure-secret-change-me-in-production!"
    jwt_issuer: str = "dinemate"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_days: int = 30
    cookie_secure: bool = False
    cookie_domain: str = ""
    # "lax" when the browser sees one site (frontend proxied onto the API's
    # origin). "none" when they are separate origins - a Vercel frontend calling
    # an API on another host - because a Lax cookie is simply not sent on a
    # cross-site request and every call comes back 401. "none" additionally
    # requires Secure, which `check_deployment` enforces rather than leaving to
    # a browser to reject silently.
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    # Domain rules (DOMAIN_MODEL.md)
    # Currency. PKR has no practical subunit, so minor_units == rupees and
    # nothing is shown after a decimal point. Arithmetic stays integer either way.
    currency_symbol: str = "Rs "
    currency_decimals: int = 0
    tax_rate: float = 0.16
    delivery_fee: int = 150  # minor units, charged per kitchen
    cancellation_window_minutes: int = 10
    confirmation_token_ttl_seconds: int = 300
    history_turns: int = 12
    memory_confidence_floor: float = 0.8

    # API
    cors_origins: list[str] = ["http://localhost:3000"]
    # Where this API is reachable from the browser. Used to tell a same-origin
    # deployment from a cross-origin one, which decides whether session cookies
    # can be SameSite=Lax or have to be SameSite=None.
    public_api_url: str = "http://localhost:8000"
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
    if s.is_production and (len(s.jwt_secret) < 32 or "dev-only" in s.jwt_secret):
        raise RuntimeError("JWT_SECRET must be set to a strong value in production")
    return s


settings = get_settings()
