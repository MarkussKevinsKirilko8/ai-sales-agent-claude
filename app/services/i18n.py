"""Internationalization with on-the-fly translation via LLM.

Translations are cached in Redis so each language is only translated once.
"""
import json
import logging

import redis.asyncio as aioredis

from app.config.settings import settings

logger = logging.getLogger(__name__)

_redis = None

# Source strings in Russian — default language
SOURCE_STRINGS = {
    "shop": "🛒 Магазин",
    "manager": "👤 Менеджер",
    "close": "❌ Закрыть чат с менеджером",
    "manager_connect": (
        "Переключаем вас на менеджера. Время ответа: до 24 часов.\n"
        "График работы: Пн-Пт 09:00-18:00 МСК.\n"
        "Напишите /close чтобы завершить чат с менеджером."
    ),
    "manager_closed": "Чат с менеджером завершён. Вы снова общаетесь с AI-ассистентом.",
    "manager_already": "Вы уже подключены к менеджеру.",
    "manager_waiting": (
        "Ваше сообщение отправлено менеджеру. "
        "Ожидайте ответа в течение 24 часов. "
        "Напишите /close чтобы вернуться к AI-ассистенту."
    ),
    "already_ai": "Вы уже общаетесь с AI-ассистентом.",
    "welcome": (
        "👋 Добро пожаловать! Я AI-ассистент по продукции в этом магазине.\n\n"
        "Задайте любой вопрос о товарах, наличии или ценах.\n\n"
        "🛒 Нажмите <b>Магазин</b> — для просмотра и заказа\n"
        "👤 Нажмите <b>Менеджер</b> — для связи с менеджером"
    ),
    "voice_fail": "Не удалось распознать голосовое сообщение. Попробуйте ещё раз или отправьте текст.",
    "other": "Отправьте текстовое или голосовое сообщение, и я помогу вам найти информацию.",
}

TRANSLATIONS_VERSION = 4


async def get_redis():
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url)
    return _redis


def _cache_key(lang: str) -> str:
    return f"i18n:v{TRANSLATIONS_VERSION}:{lang}"


async def _translate_strings(target_lang: str) -> dict:
    """Use the configured LLM to translate UI strings."""
    from app.agents.sales_agent import call_llm

    source_json = json.dumps(SOURCE_STRINGS, ensure_ascii=False, indent=2)

    prompt = (
        f"Translate the following UI strings from Russian to {target_lang}. "
        "Keep emojis, HTML tags (like <b>), and special characters (\\n, /close) exactly as they are. "
        "Return ONLY a valid JSON object with the same keys, no markdown, no explanation.\n\n"
        f"Source:\n{source_json}"
    )

    try:
        raw = await call_llm(
            system="",
            messages=[{"role": "user", "content": prompt}],
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
        )

        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            raw = raw.rsplit("```", 1)[0]
            raw = raw.strip()

        translated = json.loads(raw)
        for key in SOURCE_STRINGS:
            if key not in translated:
                translated[key] = SOURCE_STRINGS[key]
        return translated
    except Exception as e:
        logger.error(f"Translation to {target_lang} failed: {e}")
        return SOURCE_STRINGS


async def get_strings(lang: str) -> dict:
    """Get UI strings for a language. Uses Redis cache, translates on cache miss."""
    if lang.lower() in ("ru", "russian", "русский"):
        return SOURCE_STRINGS

    r = await get_redis()
    key = _cache_key(lang.lower())

    cached = await r.get(key)
    if cached:
        try:
            return json.loads(cached)
        except json.JSONDecodeError:
            pass

    logger.info(f"Translating UI to {lang} (first time)")
    translated = await _translate_strings(lang)

    await r.set(key, json.dumps(translated, ensure_ascii=False))
    return translated


def detect_language_simple(text: str) -> str:
    """Simple language detection without LLM call."""
    if not text or len(text.strip()) < 2:
        return "Russian"

    for char in text:
        if "\u0400" <= char <= "\u04ff":
            return "Russian"

    return "Russian"  # Default to Russian for this bot


async def detect_language(text: str) -> str:
    """Detect language — uses simple detection to avoid extra LLM calls."""
    return detect_language_simple(text)
