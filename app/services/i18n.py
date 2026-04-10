"""Internationalization with on-the-fly translation via Claude Haiku.

Translations are cached in Redis so each language is only translated once.
"""
import json
import logging

import anthropic
import redis.asyncio as aioredis

from app.config.settings import settings

logger = logging.getLogger(__name__)

_redis = None
_claude = anthropic.AsyncAnthropic(api_key=settings.claude_api_key)

# Source strings in English — these get translated to any language
SOURCE_STRINGS = {
    "shop": "🛒 Shop",
    "manager": "👤 Manager",
    "close": "❌ Close Manager Chat",
    "manager_connect": (
        "Connecting you with a manager. Working hours: Mon-Fri 09:00-18:00 Moscow time.\n"
        "Waiting for manager response. Chat will return to AI after 5 minutes of inactivity.\n"
        "Type /close to end."
    ),
    "manager_closed": "Manager chat closed. You're now back with the AI assistant.",
    "manager_already": "You're already connected to a manager.",
    "already_ai": "You're already chatting with the AI assistant.",
    "welcome": (
        "👋 Welcome! I'm the AI Sales Assistant for Hilma Biocare products.\n\n"
        "Ask me anything about products, availability, or pricing.\n\n"
        "🛒 Press <b>Shop</b> — to browse and order\n"
        "👤 Press <b>Manager</b> — to contact support"
    ),
    "voice_fail": "Couldn't understand the voice message. Please try again or send a text.",
    "other": "Send a text or voice message and I'll help you find information.",
}


async def get_redis():
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url)
    return _redis


def _cache_key(lang: str) -> str:
    return f"i18n:{lang}"


async def _translate_strings(target_lang: str) -> dict:
    """Use Haiku to translate all source strings to target language."""
    source_json = json.dumps(SOURCE_STRINGS, ensure_ascii=False, indent=2)

    prompt = (
        f"Translate the following UI strings from English to {target_lang}. "
        "Keep emojis, HTML tags (like <b>), and special characters (\\n, /close) exactly as they are. "
        "Return ONLY a valid JSON object with the same keys, no markdown, no explanation.\n\n"
        f"Source:\n{source_json}"
    )

    try:
        response = await _claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            raw = raw.rsplit("```", 1)[0]
            raw = raw.strip()

        translated = json.loads(raw)
        # Ensure all keys are present
        for key in SOURCE_STRINGS:
            if key not in translated:
                translated[key] = SOURCE_STRINGS[key]
        return translated
    except Exception as e:
        logger.error(f"Translation to {target_lang} failed: {e}")
        return SOURCE_STRINGS


async def get_strings(lang: str) -> dict:
    """Get UI strings for a language. Uses Redis cache, translates on cache miss."""
    if lang.lower() in ("en", "english"):
        return SOURCE_STRINGS

    r = await get_redis()
    key = _cache_key(lang.lower())

    # Try cache first
    cached = await r.get(key)
    if cached:
        try:
            return json.loads(cached)
        except json.JSONDecodeError:
            pass

    # Translate and cache
    logger.info(f"Translating UI to {lang} (first time)")
    translated = await _translate_strings(lang)

    await r.set(key, json.dumps(translated, ensure_ascii=False))
    return translated


async def detect_language(text: str) -> str:
    """Use Haiku to detect the language of the user's message."""
    if not text or len(text.strip()) < 2:
        return "Russian"

    try:
        response = await _claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=20,
            messages=[{
                "role": "user",
                "content": (
                    f"What language is this text written in? "
                    f"Respond with only the English name of the language (e.g., 'Russian', 'English', 'Latvian', 'Spanish'). "
                    f"No explanation, just the language name.\n\n"
                    f"Text: {text[:200]}"
                ),
            }],
        )
        lang = response.content[0].text.strip()
        return lang
    except Exception as e:
        logger.error(f"Language detection failed: {e}")
        return "Russian"
