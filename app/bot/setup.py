from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.bot.handlers import router
from app.config.settings import settings

# One Bot instance per configured token. bot.id is parsed from the token, so it's
# available immediately (no network call needed) for the id→Bot map.
bots = [
    Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    for token in settings.telegram_tokens
]
bots_by_id = {b.id: b for b in bots}

dp = Dispatcher()
dp.include_router(router)
