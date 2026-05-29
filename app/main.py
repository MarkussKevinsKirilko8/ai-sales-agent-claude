import asyncio
import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.bot.setup import bot, dp
from app.config.settings import settings
from app.database.session import init_db
from app.scrapers.service import run_scrapers
from app.services import bot_shops
from app.services.crm_signing import verify
from app.services.manager_mode import (
    disable_manager_mode,
    enable_manager_mode,
    sweep_expired_sessions,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# HMAC failures that are auth-related → 401; everything else → 400
_AUTH_FAILURES = {
    "crm auth not configured", "missing auth headers", "invalid api key",
    "invalid timestamp", "expired", "invalid signature",
}


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


async def manager_expiry_loop():
    """Every 60s, fire the outbound CRM 'false' event for sessions whose 24h
    TTL lapsed (Redis TTL deletion is silent, so we sweep a parallel set)."""
    await asyncio.sleep(10)
    while True:
        try:
            await sweep_expired_sessions()
        except Exception as e:
            logger.error(f"Manager expiry sweep failed: {e}")
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    app.state.redis = aioredis.from_url(settings.redis_url)

    # Cache the bot's @username (used to key CRM events) — never hardcoded
    try:
        await bot_shops.init_bot_identity(bot)
    except Exception as e:
        logger.error(f"Failed to read bot identity at startup: {e}")

    # Run bot polling in background so it doesn't block FastAPI
    polling_task = asyncio.create_task(dp.start_polling(bot, handle_signals=False))

    # Run scraper on a schedule (initial + every N hours)
    scrape_task = asyncio.create_task(scrape_loop())

    # Sweep expired manager-mode sessions (fires outbound CRM 'false')
    expiry_task = asyncio.create_task(manager_expiry_loop())

    yield

    scrape_task.cancel()
    expiry_task.cancel()

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


@app.post("/api/manager-mode")
async def manager_mode_inbound(request: Request):
    """CRM → AI: a human operator stepped in (or stepped out). Verify HMAC,
    flip the flag WITHOUT echoing back to the CRM, and notify the user."""
    from app.bot.handlers import action_buttons, close_button, get_user_lang
    from app.services.i18n import get_strings

    correlation_id = request.headers.get("x-correlation-id", "")

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "invalid json"})

    ok, reason = verify(
        body,
        settings.octo_secret,
        settings.octo_api_key,
        request.headers.get("x-octo-key"),
        request.headers.get("x-octo-timestamp"),
        request.headers.get("x-octo-signature"),
    )
    if not ok:
        status = 401 if reason in _AUTH_FAILURES else 400
        logger.warning(f"Inbound manager-mode rejected: {reason} (corr={correlation_id})")
        return JSONResponse(status_code=status, content={"error": reason})

    chat_id = body.get("chat_id")
    manager_mode = body.get("manager_mode")
    if isinstance(chat_id, bool) or not isinstance(chat_id, int):
        return JSONResponse(status_code=400, content={"error": "chat_id must be int"})
    if not isinstance(manager_mode, bool):
        return JSONResponse(status_code=400, content={"error": "manager_mode must be bool"})

    bot_username = body.get("bot_username")
    if not bot_shops.matches_primary(bot_username):
        return JSONResponse(status_code=400, content={"error": f"unknown bot_username: {bot_username}"})

    # Origin = CRM, so suppress the outbound echo
    if manager_mode:
        await enable_manager_mode(chat_id, notify_crm=False)
    else:
        await disable_manager_mode(chat_id, notify_crm=False)

    # Notify the user (with an inline close button on takeover)
    try:
        lang = await get_user_lang(chat_id)
        strings = await get_strings(lang)
        if manager_mode:
            await bot.send_message(
                chat_id=chat_id,
                text=strings["manager_connect"],
                reply_markup=close_button(strings),
            )
        else:
            await bot.send_message(
                chat_id=chat_id,
                text=strings["manager_closed"],
                reply_markup=action_buttons(strings),
            )
    except Exception as e:
        logger.error(f"Failed to notify user {chat_id} of manager-mode change: {e}")

    return {"success": True}


@app.get("/api/manager-status")
async def manager_status(chat_id: int):
    """Check if a chat is in manager mode. Used by CRM to filter messages.

    When manager_mode is true, also returns the handoff summary, user name,
    and username so the CRM can show it as the first message.
    """
    from app.services.manager_mode import is_manager_mode, get_manager_summary

    mode = await is_manager_mode(chat_id)
    response = {"chat_id": chat_id, "manager_mode": mode}

    if mode:
        summary_data = await get_manager_summary(chat_id)
        if summary_data:
            response["summary"] = summary_data.get("summary", "")
            response["user_name"] = summary_data.get("user_name", "")
            response["username"] = summary_data.get("username", "")

    return response
