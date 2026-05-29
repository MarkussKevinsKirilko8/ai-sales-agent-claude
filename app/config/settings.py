from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Telegram — bot 1 (test, no shop) + bot 2 (production, has mini-app shop)
    telegram_bot_token: str
    telegram_bot_token_2: str = ""

    @property
    def telegram_tokens(self) -> list[str]:
        """All configured bot tokens, in order."""
        return [t for t in (self.telegram_bot_token, self.telegram_bot_token_2) if t]

    # Claude API
    claude_api_key: str

    # OpenAI (Whisper)
    openai_api_key: str = ""

    # "New user joined" notification webhook (fleet-wide notification service)
    bot_start_webhook_secret: str = ""

    # Firecrawl (fallback)
    firecrawl_api_key: str = ""

    # Product API
    product_api_url: str = ""
    product_api_token: str = ""

    # PostgreSQL
    postgres_user: str = "agent"
    postgres_password: str = "changeme"
    postgres_db: str = "sales_agent"
    postgres_host: str = "db"
    postgres_port: int = 5432

    # Redis
    redis_host: str = "redis"
    redis_port: int = 6379

    # Manager group chat ID
    manager_group_id: int = -5179724701

    # OCTO CRM integration (bidirectional, HMAC-signed). Values set on host.
    crm_base_url: str = ""
    octo_api_key: str = ""
    octo_secret: str = ""

    # Sync schedule (hours between API syncs) — 6 = every 6 hours
    scrape_interval_hours: int = 6

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}"

    model_config = {"env_file": ".env"}


settings = Settings()
