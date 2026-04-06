import logging

import redis.asyncio as aioredis

from app.config.settings import settings

logger = logging.getLogger(__name__)

MANAGER_MODE_TTL = 300  # 5 minutes timeout

_redis = None


async def get_redis():
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url)
    return _redis


def _key(chat_id: int) -> str:
    return f"manager_mode:{chat_id}"


async def enable_manager_mode(chat_id: int):
    """Enable manager mode for a chat. Expires after 5 minutes."""
    r = await get_redis()
    await r.set(_key(chat_id), "1", ex=MANAGER_MODE_TTL)
    logger.info(f"Manager mode enabled for chat {chat_id}")


async def disable_manager_mode(chat_id: int):
    """Disable manager mode for a chat."""
    r = await get_redis()
    await r.delete(_key(chat_id))
    logger.info(f"Manager mode disabled for chat {chat_id}")


async def is_manager_mode(chat_id: int) -> bool:
    """Check if a chat is in manager mode."""
    r = await get_redis()
    return await r.exists(_key(chat_id)) == 1


async def refresh_manager_mode(chat_id: int):
    """Reset the 5-minute timeout (on each new message during manager mode)."""
    r = await get_redis()
    if await r.exists(_key(chat_id)):
        await r.expire(_key(chat_id), MANAGER_MODE_TTL)
