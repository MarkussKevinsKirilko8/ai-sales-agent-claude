"""Outbound AI → CRM engagement notifications.

Fires whenever a chat's manager_mode flips. Fully decoupled: scheduled as a
background task so the user's reply is never delayed, errors are logged but
never raised, retries on 5xx/network (not 4xx). No-op if CRM env vars or the
bot username are missing.
"""
import asyncio
import logging

import httpx

from app.config.settings import settings
from app.services.crm_signing import sign

logger = logging.getLogger(__name__)

SYNC_PATH = "/api/autopilot/telegram/sync"
_RETRY_BACKOFFS = [1, 2]  # seconds between attempts 1→2 and 2→3 (3 attempts total)
_TIMEOUT = 5.0

# Strong refs so fire-and-forget tasks aren't garbage-collected mid-flight.
_background_tasks: set[asyncio.Task] = set()


async def notify_engagement(chat_id: int, manager_mode: bool, bot_username: str | None) -> None:
    """POST a manager_mode flip to the CRM. Logs and swallows all errors."""
    if not (settings.crm_base_url and settings.octo_api_key and settings.octo_secret):
        logger.info("CRM not configured — skipping engagement notify")
        return
    if not bot_username:
        logger.warning("bot_username unknown — skipping engagement notify")
        return

    body = {
        "bot_username": bot_username,
        "chat_id": chat_id,
        "manager_mode": manager_mode,
    }
    timestamp, signature = sign(body, settings.octo_secret)
    headers = {
        "Content-Type": "application/json",
        "x-octo-key": settings.octo_api_key,
        "x-octo-timestamp": timestamp,
        "x-octo-signature": signature,
    }
    url = settings.crm_base_url.rstrip("/") + SYNC_PATH

    attempts = len(_RETRY_BACKOFFS) + 1
    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(url, json=body, headers=headers)
            if resp.status_code < 300:
                logger.info(f"CRM engagement sent: chat={chat_id} manager_mode={manager_mode}")
                return
            if 400 <= resp.status_code < 500:
                # Won't be fixed by retrying (validation/auth) — stop.
                logger.error(f"CRM engagement rejected ({resp.status_code}): {resp.text[:200]}")
                return
            logger.warning(f"CRM engagement {resp.status_code} (attempt {attempt + 1}/{attempts})")
        except Exception as e:
            logger.warning(f"CRM engagement error (attempt {attempt + 1}/{attempts}): {e}")

        if attempt < len(_RETRY_BACKOFFS):
            await asyncio.sleep(_RETRY_BACKOFFS[attempt])

    logger.error(f"CRM engagement failed after {attempts} attempts: chat={chat_id}")


def schedule_engagement(chat_id: int, manager_mode: bool, bot_username: str | None) -> None:
    """Schedule notify_engagement as a background task and return immediately."""
    task = asyncio.create_task(notify_engagement(chat_id, manager_mode, bot_username))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
