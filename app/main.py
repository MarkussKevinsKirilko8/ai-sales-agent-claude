import asyncio
import logging
from contextlib import asynccontextmanager
from functools import partial

import redis.asyncio as aioredis
from fastapi import FastAPI

from app.bot.setup import bot, dp
from app.config.settings import settings
from app.database.session import init_db
from app.scrapers.service import run_scrapers

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def scrape_in_thread(force: bool = False):
    """Run scrapers in a separate thread so they don't block the bot."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(asyncio.run, run_scrapers(force=force)))


async def scrape_loop():
    """Run scrapers on startup and then every N hours."""
    while True:
        try:
            count = await scrape_in_thread()
            logger.info(f"Scrape complete: {count} products")
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
    count = await scrape_in_thread(force=True)
    return {"status": "ok", "products_scraped": count}
