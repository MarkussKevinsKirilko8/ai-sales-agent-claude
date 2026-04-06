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
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    KeyboardButton,
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

# Shop URL — Telegram mini app
SHOP_URL = "https://razvedka_rf_bot.miniapp-rf.app"

# Claude client for summarization
_claude = anthropic.AsyncAnthropic(api_key=settings.claude_api_key)


def main_keyboard() -> ReplyKeyboardMarkup:
    """Reply keyboard with Shop and Manager — pinned below chat input."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🛒 Shop", web_app=WebAppInfo(url=SHOP_URL)),
                KeyboardButton(text="👤 Manager"),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Ask about products...",
    )


def manager_keyboard() -> ReplyKeyboardMarkup:
    """Reply keyboard during manager mode — only Close button."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="❌ Close Manager Chat")],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Chatting with manager...",
    )


async def summarize_conversation(history: list[dict]) -> str:
    """Use Claude Haiku to compress conversation into a short summary for the manager."""
    if not history:
        return "Новый клиент, без истории переписки."

    conversation = "\n".join(
        f"{'User' if m['role'] == 'user' else 'Bot'}: {m['content'][:300]}"
        for m in history[-8:]
    )

    try:
        response = await _claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": (
                    "Summarize this customer conversation in 2-3 sentences in Russian. "
                    "Focus on: what product(s) the customer is interested in, what they need help with, "
                    "and any important details. Be concise.\n\n"
                    f"Conversation:\n{conversation}"
                ),
            }],
        )
        return response.content[0].text
    except Exception as e:
        logger.error(f"Summary generation failed: {e}")
        return "Не удалось создать сводку. Проверьте историю чата."


async def handle_manager_start(message: types.Message, bot: Bot):
    """Start manager mode for the user."""
    await enable_manager_mode(message.chat.id)

    # Get conversation history and generate summary
    history = await get_history(message.chat.id)
    summary = await summarize_conversation(history)

    # Send summary to manager group
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

    await message.answer(
        "Переключаем вас на менеджера. График работы: Пн-Пт 09:00-18:00 МСК.\n"
        "Ожидайте ответа менеджера. Чат автоматически вернётся к AI через 5 минут без активности.\n\n"
        "Connecting you with a manager. Working hours: Mon-Fri 09:00-18:00 Moscow time.\n"
        "Waiting for manager response. Chat will return to AI after 5 minutes of inactivity.",
        reply_markup=manager_keyboard(),
    )


async def send_response(message: types.Message, bot: Bot, response: AgentResponse) -> None:
    """Send the agent response with product images."""
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
        reply_markup=main_keyboard(),
    )


@router.message(CommandStart())
async def handle_start(message: types.Message) -> None:
    """Handle /start command — show welcome message and keyboard."""
    if message.chat.type in ("group", "supergroup"):
        return
    await message.answer(
        "👋 Welcome! I'm the AI Sales Assistant for Hilma Biocare products.\n\n"
        "Ask me anything about products, availability, or pricing.\n"
        "Use the buttons below to open the Shop or contact a Manager.",
        reply_markup=main_keyboard(),
    )


@router.message(Command("close"))
async def handle_close_command(message: types.Message) -> None:
    """Handle /close command — return to AI mode from anywhere."""
    if message.chat.type in ("group", "supergroup"):
        return
    if await is_manager_mode(message.chat.id):
        await disable_manager_mode(message.chat.id)
        await message.answer(
            "Чат с менеджером завершён.\nManager chat closed.",
            reply_markup=main_keyboard(),
        )
    else:
        await message.answer("You're already chatting with the AI assistant.")


@router.message(F.text == "👤 Manager")
async def handle_manager_button(message: types.Message, bot: Bot) -> None:
    """Handle Manager button press."""
    if message.chat.type in ("group", "supergroup"):
        return
    if await is_manager_mode(message.chat.id):
        await message.answer("Вы уже подключены к менеджеру. / Already connected to manager.")
        return
    await handle_manager_start(message, bot)


@router.message(F.text == "❌ Close Manager Chat")
async def handle_close_button(message: types.Message) -> None:
    """Handle Close Manager Chat button press."""
    if message.chat.type in ("group", "supergroup"):
        return
    await disable_manager_mode(message.chat.id)
    await message.answer(
        "Чат с менеджером завершён. Вы снова общаетесь с AI-ассистентом.\n\n"
        "Manager chat closed. You're now back with the AI assistant.",
        reply_markup=main_keyboard(),
    )


@router.message(F.voice)
async def handle_voice(message: types.Message, bot: Bot) -> None:
    """Handle incoming voice messages."""
    if message.chat.type in ("group", "supergroup"):
        return

    # If in manager mode, don't process with AI
    if await is_manager_mode(message.chat.id):
        await refresh_manager_mode(message.chat.id)
        return

    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    file = await bot.get_file(message.voice.file_id)
    file_bytes = io.BytesIO()
    await bot.download_file(file.file_path, file_bytes)

    text = await transcribe_voice(file_bytes.getvalue())
    if not text:
        await message.answer(
            "Sorry, I couldn't understand the voice message. Please try again or send a text message.",
            reply_markup=main_keyboard(),
        )
        return

    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    history = await get_history(message.chat.id)
    response = await get_agent_response(text, chat_history=history)

    await add_message(message.chat.id, "user", text)
    await add_message(message.chat.id, "assistant", response.text)

    await message.answer(f"🎤 <i>{text}</i>")
    await send_response(message, bot, response)


@router.message(F.text)
async def handle_message(message: types.Message, bot: Bot) -> None:
    """Handle all incoming text messages."""
    logger.info(f"Message from chat_id={message.chat.id}, type={message.chat.type}")

    # Ignore group messages
    if message.chat.type in ("group", "supergroup"):
        return

    # If in manager mode, don't process with AI — let CRM handle
    if await is_manager_mode(message.chat.id):
        await refresh_manager_mode(message.chat.id)
        return

    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    history = await get_history(message.chat.id)
    response = await get_agent_response(message.text, chat_history=history)

    # Haiku detected manager request
    if response.wants_manager:
        await handle_manager_start(message, bot)
        return

    await add_message(message.chat.id, "user", message.text)
    await add_message(message.chat.id, "assistant", response.text)

    await send_response(message, bot, response)


@router.message()
async def handle_other(message: types.Message) -> None:
    """Handle any other message type."""
    if message.chat.type in ("group", "supergroup"):
        return

    if await is_manager_mode(message.chat.id):
        await refresh_manager_mode(message.chat.id)
        return

    await message.answer(
        "Please send a text or voice message and I'll help you find information.",
        reply_markup=main_keyboard(),
    )
