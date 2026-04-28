import asyncio
import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI

from app.bot.setup import bot, dp
from app.config.settings import settings
from app.database.session import init_db
from app.scrapers.service import run_scrapers

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def scrape_loop():
    """Run scrapers on startup and then every N hours."""
    await asyncio.sleep(5)
    first_run = True
    while True:
        try:
            count = await run_scrapers(force=not first_run)
            logger.info(f"Scrape complete: {count} products")
            first_run = False
        except Exception as e:
            logger.error(f"Scrape failed: {e}")
        await asyncio.sleep(settings.scrape_interval_hours * 3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    app.state.redis = aioredis.from_url(settings.redis_url)

    # Run bot polling in background so it doesn't block FastAPI
    polling_task = asyncio.create_task(dp.start_polling(bot, handle_signals=False))

    # Run scraper on a schedule (initial + every N hours)
    scrape_task = asyncio.create_task(scrape_loop())

    yield

    scrape_task.cancel()

    # Shutdown
    dp.shutdown.set()
    polling_task.cancel()
    await bot.session.close()
    await app.state.redis.close()


app = FastAPI(title="AI Sales Agent", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/scrape")
async def trigger_scrape():
    """Manually trigger a rescrape of all sites."""
    count = await run_scrapers(force=True)
    return {"status": "ok", "products_scraped": count}


@app.get("/api/manager-status")
async def manager_status(chat_id: int):
    """Check if a chat is in manager mode. Used by CRM to filter messages."""
    from app.services.manager_mode import is_manager_mode
    mode = await is_manager_mode(chat_id)
    return {"chat_id": chat_id, "manager_mode": mode}
