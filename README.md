# AI Sales Agent — Telegram Bot

A Telegram bot that uses Claude AI to answer product questions, handle sales inquiries, and manage customer-to-manager handoff for Hilma Biocare products.

## Tech Stack

- **Python 3.12** + FastAPI + aiogram (Telegram)
- **Claude API** — Sonnet for responses, Haiku for intent detection + translations
- **OpenAI Whisper** — voice message transcription
- **Product API** (techbz.fit) — product data, prices, stock
- **PostgreSQL** — product data storage
- **Redis** — chat history, manager mode flags, translation cache
- **Docker Compose** — containerized deployment

## Project Structure

```
app/
├── main.py                    # FastAPI app, startup, scrape loop
├── config/
│   └── settings.py            # All env vars loaded here
├── bot/
│   ├── setup.py               # Bot + dispatcher init
│   └── handlers.py            # All message/callback handlers
├── agents/
│   └── sales_agent.py         # Claude system prompt + product search
├── scrapers/
│   ├── base.py                # Firecrawl client (fallback)
│   ├── product_api.py         # Primary data source (API)
│   ├── hilmabiocare.py        # Firecrawl scraper (disabled)
│   ├── hilmabiocareshop.py    # Firecrawl scraper (disabled)
│   └── service.py             # Orchestrates scraping + DB storage
├── database/
│   ├── models.py              # SQLAlchemy models (ScrapedPage)
│   ├── session.py             # Async DB connection
│   └── queries.py             # Search functions
└── services/
    ├── voice.py               # Whisper transcription
    ├── chat_history.py        # Redis conversation history
    ├── manager_mode.py        # Manager mode flags (Redis)
    ├── formatting.py          # Markdown → Telegram HTML
    └── i18n.py                # Auto-translation (Haiku + Redis cache)
```

## Setup

### 1. Clone & configure

```bash
git clone https://github.com/MarkussKevinsKirilko8/ai-sales-agent.git
cd ai-sales-agent
cp .env.example .env
# Edit .env with your API keys
```

### 2. Required API keys (.env)

```
TELEGRAM_BOT_TOKEN=       # From @BotFather
CLAUDE_API_KEY=           # From console.anthropic.com/settings/keys
OPENAI_API_KEY=           # From platform.openai.com/api-keys
PRODUCT_API_URL=          # Product data API endpoint
PRODUCT_API_TOKEN=        # Product data API auth token
POSTGRES_USER=agent
POSTGRES_PASSWORD=        # Pick a strong password
POSTGRES_DB=sales_agent
POSTGRES_HOST=db
POSTGRES_PORT=5432
REDIS_HOST=redis
REDIS_PORT=6379
```

### 3. Run locally

```bash
docker compose up --build
```

### 4. Deploy to server

```bash
# On server (Ubuntu 24.04):
apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh
cd /opt
git clone <repo-url>
cd ai-sales-agent
nano .env  # Paste your keys
docker compose up --build -d
```

### 5. Updates

```bash
# On your Mac:
git add -A && git commit -m "description" && git push

# On server:
cd /opt/ai-sales-agent && git pull && docker compose up --build -d
```

## Useful Commands

```bash
# View logs
docker compose logs -f app

# Force re-scrape products
curl -X POST http://localhost:8000/scrape

# Check health
curl http://localhost:8000/health

# Check manager mode for a user
curl http://localhost:8000/api/manager-status?chat_id=123456

# Access database directly
docker compose exec db psql -U agent -d sales_agent

# Restart
docker compose restart app

# Stop everything
docker compose down

# Stop + delete database (fresh start)
docker compose down -v
```

---

## Lessons Learned & Tips for Future Projects

### Security — CRITICAL

1. **NEVER expose database ports publicly**
   ```yaml
   # BAD — exposes to the entire internet:
   ports:
     - "5432:5432"
     - "6379:6379"

   # GOOD — internal only (no ports: section):
   # Just remove the ports: block entirely.
   # Containers talk to each other via Docker's internal network.
   ```
   Only add `ports:` to services that NEED external access (like your API on 8000).

2. **Docker bypasses UFW** — even if UFW blocks a port, Docker's port mapping opens it anyway via iptables. Don't rely on UFW to protect Docker services.

3. **Use .env for secrets** — never commit API keys to git. Always have `.env` in `.gitignore`.

4. **Rotate API keys** if you ever accidentally expose them (in screenshots, git commits, chat logs, etc.).

### Docker & Deployment

5. **Pin package versions** in requirements.txt — don't use `>=` or leave versions open. Exact pins prevent surprise breakages.

6. **Check dependency conflicts early** — run `pip install -r requirements.txt` locally before building Docker. Saves time vs discovering conflicts during `docker compose build`.

7. **Use `docker compose up --build -d`** for deploys — the `-d` flag runs in background, `--build` ensures code changes are picked up.

8. **Don't use volume mounts on production** — `volumes: .:/app` is great for local dev but causes permission issues on servers. We learned this the hard way.

9. **Always use `docker compose down -v` when changing database schemas** — the `-v` flag removes the PostgreSQL data volume so tables get recreated. Without it, new columns won't exist.

### Telegram Bot

10. **Reply keyboards are unreliable on desktop** — they collapse when you tap the text input. Use inline buttons (attached to messages) for anything critical. They never disappear.

11. **Only one bot can poll at a time** — if both your code and a CRM use the same bot token, one will steal messages from the other. Design around this (we used an API endpoint for the CRM to check manager status).

12. **WebApp buttons have a small icon** — `web_app=WebAppInfo(url=...)` shows a mini square icon on the button. You can't remove it. Use `url=` for plain buttons (but loses mini app features).

13. **Telegram limits caption length to 1024 chars** — don't try to stuff product descriptions into photo captions.

14. **Use `link_preview_options=LinkPreviewOptions(is_disabled=True)`** on text messages — otherwise Telegram generates preview cards for any URL in the text, which looks cluttered.

### AI / Claude

15. **Use Haiku for fast tasks** — intent detection, language detection, translation, product name extraction. It's cheap (~$0.25/M tokens) and fast. Use Sonnet only for the main response.

16. **Don't dump all data into the system prompt** — we started by sending all 55 products to Claude on every message. This hit rate limits instantly. Search first, send only relevant products.

17. **System prompts need to be VERY explicit** — Claude will add "helpful" extras (usage instructions, medical disclaimers, emoji) unless you explicitly say "DO NOT include X." Be strict.

18. **Conversation history costs tokens** — each stored message adds to every future API call. Cap it (we use 10 messages max, 1 hour expiry).

19. **Cache translations** — don't re-translate UI strings on every message. Store in Redis with a version key so you can invalidate when source strings change.

### Web Scraping

20. **APIs > scraping** — if the data source has an API, use it. We switched from Firecrawl (slow, expensive, unreliable) to a product API (fast, free, structured). Night and day difference.

21. **Sitemaps are your friend** — WordPress sites have `/wp-sitemap.xml` which lists all pages. Much more reliable than crawling category pages.

22. **JavaScript-rendered content needs wait time** — if using Firecrawl, add `waitFor: 3000` to let JS load. Without it, you get empty pages.

23. **onlyMainContent can strip too much** — Firecrawl's `onlyMainContent: true` sometimes removes the actual product specs. Test both with and without.

24. **Scraping is fragile** — sites change, go down, block you. Always have a fallback. We kept Firecrawl code commented out as a backup.

### Architecture

25. **Don't run scraping on the main event loop** — synchronous HTTP calls block the entire bot. Use `loop.run_in_executor()` to run them in a thread pool.

26. **Skip scraping if data exists** — check the database before scraping on startup. Saves API credits and startup time.

27. **Version your caches** — when cached data format changes, bump a version number in the cache key (e.g., `i18n:v2:Russian`). Otherwise stale cache causes bugs.

28. **Separate concerns** — bot handlers should be thin. Business logic goes in agents/services. This makes it easy to change the bot framework without rewriting everything.
