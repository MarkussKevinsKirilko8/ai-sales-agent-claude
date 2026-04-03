import json
import logging

import redis.asyncio as aioredis

from app.config.settings import settings

logger = logging.getLogger(__name__)

MAX_HISTORY = 10  # Keep last 10 messages (5 user + 5 assistant)

_redis = None


async def get_redis():
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url)
    return _redis


def _key(chat_id: int) -> str:
    return f"chat_history:{chat_id}"


async def get_history(chat_id: int) -> list[dict]:
    """Get conversation history for a chat."""
    r = await get_redis()
    raw = await r.get(_key(chat_id))
    if not raw:
        return []
    return json.loads(raw)


async def add_message(chat_id: int, role: str, content: str):
    """Add a message to the conversation history."""
    r = await get_redis()
    history = await get_history(chat_id)
    history.append({"role": role, "content": content})

    # Keep only the last N messages
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]

    await r.set(_key(chat_id), json.dumps(history), ex=3600)  # Expire after 1 hour
