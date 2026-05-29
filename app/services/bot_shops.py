"""Bot identity cache.

The bot's @username is read from Telegram via getMe at startup (never
hardcoded) — the CRM integration keys events by bot_username. This project
runs a single bot token; the helpers are structured so multi-bot routing can
be added later without changing call sites.
"""
import logging

from aiogram import Bot

logger = logging.getLogger(__name__)

_primary_username: str | None = None
_primary_bot_id: int | None = None


async def init_bot_identity(bot: Bot) -> None:
    """Fetch and cache the bot's username + id. Call once at startup."""
    global _primary_username, _primary_bot_id
    me = await bot.get_me()
    _primary_username = me.username
    _primary_bot_id = me.id
    logger.info(f"Bot identity cached: @{_primary_username} (id={_primary_bot_id})")


def get_primary_username() -> str | None:
    return _primary_username


def get_primary_bot_id() -> int | None:
    return _primary_bot_id


def matches_primary(bot_username: str | None) -> bool:
    """True if the given username refers to this bot. Empty/None → primary
    (back-compat: CRM may omit bot_username for single-bot deployments).
    Case-insensitive, leading @ optional.
    """
    if not bot_username:
        return True
    if not _primary_username:
        return False
    return bot_username.lstrip("@").lower() == _primary_username.lower()
