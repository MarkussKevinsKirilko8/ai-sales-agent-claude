import json
import logging

import redis.asyncio as aioredis

from app.config.settings import settings

logger = logging.getLogger(__name__)

MANAGER_MODE_TTL = 86400  # 24 hours timeout

_redis = None


async def get_redis():
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url)
    return _redis


def _key(chat_id: int) -> str:
    return f"manager_mode:{chat_id}"


def _close_btn_key(chat_id: int) -> str:
    return f"manager_close_btn:{chat_id}"


def _summary_key(chat_id: int) -> str:
    return f"manager_summary:{chat_id}"


async def enable_manager_mode(chat_id: int):
    """Enable manager mode for a chat. Expires after 24 hours."""
    r = await get_redis()
    await r.set(_key(chat_id), "1", ex=MANAGER_MODE_TTL)
    await r.delete(_msg_count_key(chat_id))
    logger.info(f"Manager mode enabled for chat {chat_id}")


async def disable_manager_mode(chat_id: int):
    """Disable manager mode for a chat."""
    r = await get_redis()
    await r.delete(_key(chat_id))
    await r.delete(_close_btn_key(chat_id))
    await r.delete(_msg_count_key(chat_id))
    await r.delete(_summary_key(chat_id))
    logger.info(f"Manager mode disabled for chat {chat_id}")


async def save_manager_summary(chat_id: int, summary: str, user_name: str = "", username: str = ""):
    """Save the handoff summary so the CRM can fetch it via the API."""
    r = await get_redis()
    payload = json.dumps({
        "summary": summary,
        "user_name": user_name,
        "username": username,
    }, ensure_ascii=False)
    await r.set(_summary_key(chat_id), payload, ex=MANAGER_MODE_TTL)


async def get_manager_summary(chat_id: int) -> dict | None:
    """Get the saved summary for the CRM."""
    r = await get_redis()
    raw = await r.get(_summary_key(chat_id))
    if not raw:
        return None
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.error(f"Failed to parse manager summary for {chat_id}: {e}")
        return None


async def is_manager_mode(chat_id: int) -> bool:
    """Check if a chat is in manager mode."""
    r = await get_redis()
    return await r.exists(_key(chat_id)) == 1


def _msg_count_key(chat_id: int) -> str:
    return f"manager_msg_count:{chat_id}"


async def refresh_manager_mode(chat_id: int) -> int:
    """Reset the 24-hour timeout and increment message count.
    Returns the number of messages sent during this manager session.
    """
    r = await get_redis()
    if await r.exists(_key(chat_id)):
        await r.expire(_key(chat_id), MANAGER_MODE_TTL)
        count = await r.incr(_msg_count_key(chat_id))
        await r.expire(_msg_count_key(chat_id), MANAGER_MODE_TTL)
        return count
    return 0


async def save_close_button_id(chat_id: int, message_id: int):
    """Save the message ID of the last Close button."""
    r = await get_redis()
    await r.set(_close_btn_key(chat_id), str(message_id), ex=MANAGER_MODE_TTL)


async def get_close_button_id(chat_id: int) -> int | None:
    """Get the message ID of the last Close button."""
    r = await get_redis()
    msg_id = await r.get(_close_btn_key(chat_id))
    return int(msg_id) if msg_id else None
