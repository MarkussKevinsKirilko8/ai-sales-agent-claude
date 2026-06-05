"""Fire-and-forget "new user joined" notification to the fleet notification service.

Fires only on a user's FIRST ever /start (the first-time gate lives in the
caller — see app.database.queries.mark_user_seen). Fully decoupled from the
/start reply: scheduled as a background task so a slow or down notification
service never delays the user's first message. All errors are logged and
swallowed — this must never raise into the bot flow.
"""
import asyncio
import logging

import httpx
from aiogram import types

from app.config.settings import settings
from app.services import bot_shops

logger = logging.getLogger(__name__)

# bot_name stays fixed for the whole fleet; per-bot identification in the daily
# digest comes from the optional bot_handle field (looked up via bot_shops).
BOT_NAME = "Sales Agent Claude"

# Keep strong references to in-flight tasks so they aren't garbage-collected
# mid-flight. add_done_callback(discard) removes them when they finish.
_background_tasks: set[asyncio.Task] = set()


async def notify_bot_start(user: types.User, bot_id: int) -> None:
    """POST the new-user payload. Logs and swallows every error; never raises."""
    secret = settings.bot_start_webhook_secret
    if not (secret and settings.bot_start_webhook_url):
        logger.info("BOT_START_WEBHOOK_* not configured — skipping new-user notification")
        return

    payload = {
        "bot_name": BOT_NAME,
        "telegram_user_id": user.id,
        "telegram_username": user.username,
        "telegram_first_name": user.first_name,
        "telegram_last_name": user.last_name,
    }

    # Optional: per-bot display name for the digest. Skip the field entirely
    # if no handle is configured for this bot — server treats absence as "no
    # handle segment in this row," which is fine.
    handle = bot_shops.handle_for_bot(bot_id)
    if handle:
        payload["bot_handle"] = handle

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                settings.bot_start_webhook_url,
                json=payload,
                headers={"Authorization": f"Bearer {secret}"},
            )
        if response.status_code == 200:
            logger.info(f"New-user notification sent for {user.id} (bot={bot_id} handle={handle or 'none'})")
        else:
            logger.error(
                f"New-user notification failed ({response.status_code}): "
                f"{response.text[:200]}"
            )
    except Exception as e:
        logger.error(f"New-user notification error for {user.id}: {e}")


def schedule_bot_start_notification(user: types.User, bot_id: int) -> None:
    """Schedule notify_bot_start as a background task and return immediately."""
    task = asyncio.create_task(notify_bot_start(user, bot_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
