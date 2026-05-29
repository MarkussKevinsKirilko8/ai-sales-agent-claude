"""Per-bot identity + shop registry.

This project runs multiple Telegram bots on one codebase. For each bot we cache,
read from Telegram at startup (never hardcoded):
  - username (via getMe) — used to key CRM events
  - shop base URL (via getChatMenuButton) — the bot's mini-app, if it has one

A bot with no mini-app menu button (e.g. the test bot) has shop_url = None, and
the UI shows no Shop button for it.
"""
import logging
from dataclasses import dataclass

from aiogram import Bot

logger = logging.getLogger(__name__)


@dataclass
class BotInfo:
    bot_id: int
    username: str
    shop_url: str | None


# bot_id -> BotInfo
_registry: dict[int, BotInfo] = {}


async def init_bot_identity(bot: Bot) -> None:
    """Fetch and cache a bot's username + shop URL. Call once per bot at startup."""
    me = await bot.get_me()
    shop_url = None
    try:
        menu = await bot.get_chat_menu_button()
        # aiogram returns a MenuButtonWebApp when a mini-app is configured
        web_app = getattr(menu, "web_app", None)
        if web_app and getattr(web_app, "url", None):
            shop_url = web_app.url
    except Exception as e:
        logger.warning(f"Could not read menu button for @{me.username}: {e}")

    _registry[bot.id] = BotInfo(bot_id=bot.id, username=me.username, shop_url=shop_url)
    logger.info(f"Bot registered: @{me.username} (id={bot.id}) shop={shop_url or 'none'}")


def username_for_bot(bot_id: int) -> str | None:
    info = _registry.get(bot_id)
    return info.username if info else None


def shop_url_for_bot(bot_id: int) -> str | None:
    info = _registry.get(bot_id)
    return info.shop_url if info else None


def bot_id_for_username(bot_username: str | None) -> int | None:
    """Resolve a CRM-supplied bot_username to a bot_id. Empty/None → the first
    registered bot (back-compat for single-bot CRM calls). Case-insensitive,
    leading @ optional. Unknown username → None."""
    if not bot_username:
        return next(iter(_registry), None)
    target = bot_username.lstrip("@").lower()
    for info in _registry.values():
        if info.username and info.username.lower() == target:
            return info.bot_id
    return None


def all_bot_ids() -> list[int]:
    return list(_registry)
