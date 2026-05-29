import json
import logging
import time

import redis.asyncio as aioredis

from app.config.settings import settings
from app.services import bot_shops
from app.services.crm_client import schedule_engagement

logger = logging.getLogger(__name__)

MANAGER_MODE_TTL = 86400  # 24 hours timeout

# Parallel sorted set tracking each session's expiry. Redis TTL deletion is
# silent, so this lets a background sweep detect lapsed sessions and fire the
# outbound CRM "false" event. Member = "{bot_id}:{chat_id}", score = expiry ts.
EXPIRY_ZSET = "manager_mode_expiry"

_redis = None


async def get_redis():
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url)
    return _redis


# All keys are scoped by bot_id so two bots sharing one Redis never collide for
# the same Telegram user.
def _key(bot_id: int, chat_id: int) -> str:
    return f"manager_mode:{bot_id}:{chat_id}"


def _close_btn_key(bot_id: int, chat_id: int) -> str:
    return f"manager_close_btn:{bot_id}:{chat_id}"


def _summary_key(bot_id: int, chat_id: int) -> str:
    return f"manager_summary:{bot_id}:{chat_id}"


def _msg_count_key(bot_id: int, chat_id: int) -> str:
    return f"manager_msg_count:{bot_id}:{chat_id}"


def _member(bot_id: int, chat_id: int) -> str:
    return f"{bot_id}:{chat_id}"


async def enable_manager_mode(bot_id: int, chat_id: int, notify_crm: bool = True):
    """Enable manager mode for a chat. Expires after 24 hours.

    notify_crm=False suppresses the outbound CRM event — used when the flip was
    *caused by* an inbound CRM call, so we don't bounce an echo back.
    """
    r = await get_redis()
    await r.set(_key(bot_id, chat_id), "1", ex=MANAGER_MODE_TTL)
    await r.delete(_msg_count_key(bot_id, chat_id))
    await r.zadd(EXPIRY_ZSET, {_member(bot_id, chat_id): time.time() + MANAGER_MODE_TTL})
    logger.info(f"Manager mode enabled bot={bot_id} chat={chat_id} (notify_crm={notify_crm})")
    if notify_crm:
        schedule_engagement(chat_id, True, bot_shops.username_for_bot(bot_id))


async def disable_manager_mode(bot_id: int, chat_id: int, notify_crm: bool = True):
    """Disable manager mode for a chat."""
    r = await get_redis()
    await r.delete(_key(bot_id, chat_id))
    await r.delete(_close_btn_key(bot_id, chat_id))
    await r.delete(_msg_count_key(bot_id, chat_id))
    await r.delete(_summary_key(bot_id, chat_id))
    await r.zrem(EXPIRY_ZSET, _member(bot_id, chat_id))
    logger.info(f"Manager mode disabled bot={bot_id} chat={chat_id} (notify_crm={notify_crm})")
    if notify_crm:
        schedule_engagement(chat_id, False, bot_shops.username_for_bot(bot_id))


async def save_manager_summary(bot_id: int, chat_id: int, summary: str, user_name: str = "", username: str = ""):
    """Save the handoff summary so the CRM can fetch it via the API."""
    r = await get_redis()
    payload = json.dumps({
        "summary": summary,
        "user_name": user_name,
        "username": username,
    }, ensure_ascii=False)
    await r.set(_summary_key(bot_id, chat_id), payload, ex=MANAGER_MODE_TTL)


async def get_manager_summary(bot_id: int, chat_id: int) -> dict | None:
    """Get the saved summary for the CRM."""
    r = await get_redis()
    raw = await r.get(_summary_key(bot_id, chat_id))
    if not raw:
        return None
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.error(f"Failed to parse manager summary for {bot_id}:{chat_id}: {e}")
        return None


async def is_manager_mode(bot_id: int, chat_id: int) -> bool:
    """Check if a chat is in manager mode."""
    r = await get_redis()
    return await r.exists(_key(bot_id, chat_id)) == 1


async def refresh_manager_mode(bot_id: int, chat_id: int) -> int:
    """Reset the 24-hour timeout (key + expiry set) and increment message count.
    Returns the number of messages sent during this manager session.
    """
    r = await get_redis()
    if await r.exists(_key(bot_id, chat_id)):
        await r.expire(_key(bot_id, chat_id), MANAGER_MODE_TTL)
        await r.zadd(EXPIRY_ZSET, {_member(bot_id, chat_id): time.time() + MANAGER_MODE_TTL})
        count = await r.incr(_msg_count_key(bot_id, chat_id))
        await r.expire(_msg_count_key(bot_id, chat_id), MANAGER_MODE_TTL)
        return count
    return 0


async def sweep_expired_sessions() -> list[tuple[int, int]]:
    """Find sessions whose 24h TTL lapsed, clear them, and fire the outbound
    CRM "false" event for each. Returns the expired (bot_id, chat_id) pairs.

    disable_manager_mode() removes the expiry-set entry, so a swept session
    can't be processed (or double-fired) on the next sweep.
    """
    r = await get_redis()
    now = time.time()
    members = await r.zrangebyscore(EXPIRY_ZSET, min=0, max=now)
    expired = []
    for member in members:
        member = member.decode("utf-8") if isinstance(member, bytes) else member
        try:
            bot_id_str, chat_id_str = member.split(":", 1)
            bot_id, chat_id = int(bot_id_str), int(chat_id_str)
        except ValueError:
            await r.zrem(EXPIRY_ZSET, member)  # malformed legacy entry
            continue
        await disable_manager_mode(bot_id, chat_id, notify_crm=True)
        expired.append((bot_id, chat_id))
    if expired:
        logger.info(f"Swept {len(expired)} expired manager session(s): {expired}")
    return expired
