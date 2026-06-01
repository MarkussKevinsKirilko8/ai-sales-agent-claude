import os
import re

from pydantic_settings import BaseSettings


# Match TELEGRAM_BOT_TOKEN_<digits> (the primary TELEGRAM_BOT_TOKEN is read
# directly from the model field — this is for the numbered extras).
_TOKEN_SUFFIX_RE = re.compile(r"^TELEGRAM_BOT_TOKEN_(\d+)$")


class Settings(BaseSettings):
    # Telegram — primary bot token is required. Additional bots can be added by
    # setting TELEGRAM_BOT_TOKEN_2, TELEGRAM_BOT_TOKEN_3, … with ANY numeric
    # suffix (no upper limit). They're picked up dynamically from env.
    telegram_bot_token: str

    # Bots that are AI-only: no Manager button, no CRM events (comma-separated
    # usernames, @ optional). Defaults to the test bot.
    ai_only_bots: str = "sales_ai_agent_claude_bot"

    # Bots that had existing users BEFORE we added the AI. For these, an
    # unrecognized user's FIRST non-/start interaction is treated as an existing
    # customer in manager mode + an "AI added — tap to switch" prompt
    # (comma-separated usernames, @ optional).
    opt_in_bots: str = ""

    @property
    def telegram_tokens(self) -> list[str]:
        """All configured bot tokens, in order.

        Returns the primary TELEGRAM_BOT_TOKEN first, then any TELEGRAM_BOT_TOKEN_N
        (N is any positive integer) found in env, sorted by N. Add as many bots
        as you want — no code change required to bump the count.
        """
        tokens = [self.telegram_bot_token] if self.telegram_bot_token else []
        suffixed: list[tuple[int, str]] = []
        for key, val in os.environ.items():
            m = _TOKEN_SUFFIX_RE.match(key)
            if m and val and val.strip():
                suffixed.append((int(m.group(1)), val.strip()))
        suffixed.sort()
        tokens.extend(v for _, v in suffixed)
        return tokens

    @property
    def ai_only_bot_set(self) -> set[str]:
        return {b.strip().lstrip("@").lower() for b in self.ai_only_bots.split(",") if b.strip()}

    @property
    def opt_in_bot_set(self) -> set[str]:
        return {b.strip().lstrip("@").lower() for b in self.opt_in_bots.split(",") if b.strip()}

    # Claude API
    claude_api_key: str

    # OpenAI (Whisper)
    openai_api_key: str = ""

    # "New user joined" notification webhook (fleet-wide notification service).
    # URL + secret set on host; webhook skips if either is unset.
    bot_start_webhook_url: str = ""
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

    # extra="ignore" so undeclared env vars (like the dynamically-scanned
    # TELEGRAM_BOT_TOKEN_2/3/…) don't trigger Pydantic validation errors.
    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
