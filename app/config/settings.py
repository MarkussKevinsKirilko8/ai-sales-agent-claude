from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Telegram
    telegram_bot_token: str

    # Claude API (optional if using ollama)
    claude_api_key: str = ""

    # OpenAI (Whisper)
    openai_api_key: str = ""

    # LLM provider: "anthropic" or "ollama"
    llm_provider: str = "anthropic"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"

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
