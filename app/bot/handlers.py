import io
import logging

import anthropic
from aiogram import Bot, F, Router, types
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    MenuButtonDefault,
    WebAppInfo,
)

from app.agents.sales_agent import AgentResponse, get_agent_response
from app.config.settings import settings
from app.services.chat_history import add_message, get_history
from app.services.formatting import markdown_to_telegram_html
from app.services.manager_mode import (
    enable_manager_mode,
    disable_manager_mode,
    is_manager_mode,
    refresh_manager_mode,
)
from app.services.voice import transcribe_voice

router = Router()
logger = logging.getLogger(__name__)

SHOP_URL = "https://razvedka_rf_bot.miniapp-rf.app"

_claude = anthropic.AsyncAnthropic(api_key=settings.claude_api_key)

# Language strings
STRINGS = {
    "ru": {
        "shop": "🛒 Магазин",
        "manager": "👤 Менеджер",
        "close": "❌ Закрыть чат с менеджером",
        "manager_connect": (
            "Переключаем вас на менеджера. График работы: Пн-Пт 09:00-18:00 МСК.\n"
            "Ожидайте ответа менеджера. Чат автоматически вернётся к AI через 5 минут без активности.\n"
            "Напишите /close для завершения."
        ),
        "manager_closed": "Чат с менеджером завершён. Вы снова общаетесь с AI-ассистентом.",
        "manager_already": "Вы уже подключены к менеджеру.",
        "already_ai": "Вы уже общаетесь с AI-ассистентом.",
        "welcome": (
            "👋 Добро пожаловать! Я AI-ассистент по продукции Hilma Biocare.\n\n"
            "Задайте любой вопрос о продуктах, наличии или ценах.\n\n"
            "🛒 Нажмите <b>Магазин</b> — для просмотра и заказа\n"
            "👤 Нажмите <b>Менеджер</b> — для связи с менеджером"
        ),
        "voice_fail": "Не удалось распознать голосовое сообщение. Попробуйте ещё раз или отправьте текст.",
        "other": "Отправьте текстовое или голосовое сообщение, и я помогу вам найти информацию.",
    },
    "en": {
        "shop": "🛒 Shop",
        "manager": "👤 Manager",
        "close": "❌ Close Manager Chat",
        "manager_connect": (
            "Connecting you with a manager. Working hours: Mon-Fri 09:00-18:00 Moscow time.\n"
            "Waiting for manager response. Chat will return to AI after 5 minutes of inactivity.\n"
            "Type /close to end."
        ),
        "manager_closed": "Manager chat closed. You're now back with the AI assistant.",
        "manager_already": "Already connected to manager.",
        "already_ai": "You're already chatting with the AI assistant.",
        "welcome": (
            "👋 Welcome! I'm the AI Sales Assistant for Hilma Biocare products.\n\n"
            "Ask me anything about products, availability, or pricing.\n\n"
            "🛒 Press <b>Shop</b> — to browse and order\n"
            "👤 Press <b>Manager</b> — to contact support"
        ),
        "voice_fail": "Couldn't understand the voice message. Please try again or send a text.",
        "other": "Send a text or voice message and I'll help you find information.",
    },
}


def detect_lang(text: str) -> str:
    """Simple check: if text has Cyrillic characters, it's Russian."""
    for char in text:
        if "\u0400" <= char <= "\u04ff":
            return "ru"
    return "en"


def get_strings(lang: str) -> dict:
    return STRINGS.get(lang, STRINGS["ru"])


def action_buttons(lang: str = "ru") -> InlineKeyboardMarkup:
    s = get_strings(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=s["shop"], web_app=WebAppInfo(url=SHOP_URL)),
            InlineKeyboardButton(text=s["manager"], callback_data="request_manager"),
        ]
    ])


def close_button(lang: str = "ru") -> InlineKeyboardMarkup:
    s = get_strings(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=s["close"], callback_data="close_manager")]
    ])


async def summarize_conversation(history: list[dict], lang: str = "ru") -> str:
    if not history:
        return "Новый клиент, без истории переписки." if lang == "ru" else "New customer, no chat history."

    conversation = "\n".join(
        f"{'User' if m['role'] == 'user' else 'Bot'}: {m['content'][:300]}"
        for m in history[-8:]
    )

    summary_lang = "Russian" if lang == "ru" else "English"
    try:
        response = await _claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": (
                    f"Summarize this customer conversation in 2-3 sentences in {summary_lang}. "
                    "Focus on: what product(s) the customer is interested in, what they need help with, "
                    "and any important details. Be concise.\n\n"
                    f"Conversation:\n{conversation}"
                ),
            }],
        )
        return response.content[0].text
    except Exception as e:
        logger.error(f"Summary generation failed: {e}")
        return "Не удалось создать сводку." if lang == "ru" else "Could not generate summary."


async def handle_manager_start(message: types.Message, bot: Bot, lang: str = "ru"):
    await enable_manager_mode(message.chat.id)

    history = await get_history(message.chat.id)
    summary = await summarize_conversation(history, lang)

    user = message.from_user
    user_info = f"{user.full_name}"
    if user.username:
        user_info += f" (@{user.username})"

    manager_message = (
        f"📋 <b>Запрос на менеджера</b>\n\n"
        f"👤 Клиент: {user_info}\n"
        f"🆔 Chat ID: <code>{message.chat.id}</code>\n\n"
        f"📝 <b>Сводка:</b>\n{summary}"
    )

    try:
        await bot.send_message(
            chat_id=settings.manager_group_id,
            text=manager_message,
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Failed to send to manager group: {e}")

    s = get_strings(lang)
    await message.answer(
        s["manager_connect"],
        reply_markup=close_button(lang),
    )


async def send_response(message: types.Message, bot: Bot, response: AgentResponse, lang: str = "ru") -> None:
    formatted_text = markdown_to_telegram_html(response.text)

    if response.product_images:
        for product in response.product_images[:3]:
            try:
                await bot.send_photo(
                    chat_id=message.chat.id,
                    photo=product["image_url"],
                    caption=f"<b>{product['title']}</b>",
                    parse_mode="HTML",
                )
            except Exception:
                pass

    await message.answer(
        formatted_text,
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True),
        reply_markup=action_buttons(lang),
    )


@router.message(CommandStart())
async def handle_start(message: types.Message, bot: Bot) -> None:
    if message.chat.type in ("group", "supergroup"):
        return

    # Remove the menu button next to chat input
    try:
        await bot.set_chat_menu_button(menu_button=MenuButtonDefault())
    except Exception:
        pass

    s = get_strings("ru")
    await message.answer(
        s["welcome"],
        parse_mode="HTML",
        reply_markup=action_buttons("ru"),
    )


@router.message(Command("close"))
async def handle_close_command(message: types.Message) -> None:
    if message.chat.type in ("group", "supergroup"):
        return

    lang = detect_lang(message.text or "")

    if await is_manager_mode(message.chat.id):
        await disable_manager_mode(message.chat.id)
        s = get_strings(lang)
        await message.answer(
            s["manager_closed"],
            reply_markup=action_buttons(lang),
        )
    else:
        s = get_strings(lang)
        await message.answer(s["already_ai"])


@router.callback_query(F.data == "request_manager")
async def handle_manager_callback(callback: types.CallbackQuery, bot: Bot) -> None:
    if await is_manager_mode(callback.message.chat.id):
        await callback.answer("Вы уже подключены к менеджеру")
        return
    await callback.answer()

    # Detect language from recent history
    history = await get_history(callback.message.chat.id)
    lang = "ru"
    if history:
        last_user = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")
        lang = detect_lang(last_user)

    await handle_manager_start(callback.message, bot, lang)


@router.callback_query(F.data == "close_manager")
async def handle_close_manager(callback: types.CallbackQuery) -> None:
    await disable_manager_mode(callback.message.chat.id)
    await callback.answer()

    # Detect language from recent history
    history = await get_history(callback.message.chat.id)
    lang = "ru"
    if history:
        last_user = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")
        lang = detect_lang(last_user)

    s = get_strings(lang)
    await callback.message.edit_text(
        s["manager_closed"],
    )
    await callback.message.answer(
        s["manager_closed"],
        reply_markup=action_buttons(lang),
    )


@router.message(F.voice)
async def handle_voice(message: types.Message, bot: Bot) -> None:
    if message.chat.type in ("group", "supergroup"):
        return

    if await is_manager_mode(message.chat.id):
        await refresh_manager_mode(message.chat.id)
        return

    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    file = await bot.get_file(message.voice.file_id)
    file_bytes = io.BytesIO()
    await bot.download_file(file.file_path, file_bytes)

    text = await transcribe_voice(file_bytes.getvalue())
    if not text:
        s = get_strings("ru")
        await message.answer(s["voice_fail"], reply_markup=action_buttons("ru"))
        return

    lang = detect_lang(text)

    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    history = await get_history(message.chat.id)
    response = await get_agent_response(text, chat_history=history)

    await add_message(message.chat.id, "user", text)
    await add_message(message.chat.id, "assistant", response.text)

    await message.answer(f"🎤 <i>{text}</i>")
    await send_response(message, bot, response, lang)


@router.message(F.text)
async def handle_message(message: types.Message, bot: Bot) -> None:
    logger.info(f"Message from chat_id={message.chat.id}, type={message.chat.type}")

    if message.chat.type in ("group", "supergroup"):
        return

    if await is_manager_mode(message.chat.id):
        await refresh_manager_mode(message.chat.id)
        return

    lang = detect_lang(message.text)

    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    history = await get_history(message.chat.id)
    response = await get_agent_response(message.text, chat_history=history)

    if response.wants_manager:
        await handle_manager_start(message, bot, lang)
        return

    await add_message(message.chat.id, "user", message.text)
    await add_message(message.chat.id, "assistant", response.text)

    await send_response(message, bot, response, lang)


@router.message()
async def handle_other(message: types.Message) -> None:
    if message.chat.type in ("group", "supergroup"):
        return

    if await is_manager_mode(message.chat.id):
        await refresh_manager_mode(message.chat.id)
        return

    s = get_strings("ru")
    await message.answer(s["other"], reply_markup=action_buttons("ru"))
