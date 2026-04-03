from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Telegram
    telegram_bot_token: str

    # Claude API
    claude_api_key: str

    # OpenAI (Whisper)
    openai_api_key: str

    # Firecrawl
    firecrawl_api_key: str

    # PostgreSQL
    postgres_user: str = "agent"
    postgres_password: str = "changeme"
    postgres_db: str = "sales_agent"
    postgres_host: str = "db"
    postgres_port: int = 5432

    # Redis
    redis_host: str = "redis"
    redis_port: int = 6379

    # Scraper schedule (hours between scrapes) — 168 = once per week
    scrape_interval_hours: int = 168

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
