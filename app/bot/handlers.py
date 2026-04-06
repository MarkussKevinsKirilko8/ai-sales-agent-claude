import io

from aiogram import Bot, F, Router, types
from aiogram.enums import ChatAction
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    ReplyKeyboardMarkup,
    KeyboardButton,
)

from app.agents.sales_agent import AgentResponse, get_agent_response
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

# Shop URL — Telegram mini app
SHOP_URL = "https://razvedka_rf_bot.miniapp-rf.app"

# Manager trigger words
MANAGER_TRIGGERS = {"менеджер", "manager", "менеджера", "оператор", "operator"}


def main_keyboard() -> ReplyKeyboardMarkup:
    """Main persistent keyboard with Shop and Manager buttons."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛒 Shop"), KeyboardButton(text="👤 Manager")],
        ],
        resize_keyboard=True,
    )


def manager_mode_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard shown during manager mode with Close button."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="❌ Close")],
        ],
        resize_keyboard=True,
    )


def shop_inline_button() -> InlineKeyboardMarkup:
    """Inline Shop button for product responses."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Open Shop", url=SHOP_URL)]
    ])


def is_manager_request(text: str) -> bool:
    """Check if the user wants to speak with a manager."""
    cleaned = text.strip().lower().replace("👤 ", "")
    return cleaned in MANAGER_TRIGGERS


async def handle_manager_start(message: types.Message):
    """Start manager mode for the user."""
    await enable_manager_mode(message.chat.id)

    # Get recent conversation to send as context
    history = await get_history(message.chat.id)
    summary_parts = []
    for msg in history[-6:]:  # Last 3 exchanges
        role = "👤 User" if msg["role"] == "user" else "🤖 Bot"
        summary_parts.append(f"{role}: {msg['content'][:200]}")

    summary = "\n".join(summary_parts) if summary_parts else "No prior conversation."

    # TODO: Send this summary to CRM webhook when available
    # For now, log it
    import logging
    logging.getLogger(__name__).info(
        f"Manager mode activated for chat {message.chat.id}. "
        f"Conversation summary:\n{summary}"
    )

    await message.answer(
        "Переключаем вас на менеджера. График работы: Пн-Пт 09:00-18:00 МСК.\n"
        "Ожидайте ответа менеджера. Чат автоматически вернётся к AI через 5 минут без активности "
        "или нажмите кнопку \"❌ Close\".\n\n"
        "Connecting you with a manager. Working hours: Mon-Fri 09:00-18:00 Moscow time.\n"
        "Waiting for manager response. Chat will return to AI after 5 minutes of inactivity "
        "or press \"❌ Close\".",
        reply_markup=manager_mode_keyboard(),
    )


async def send_response(message: types.Message, bot: Bot, response: AgentResponse) -> None:
    """Send the agent response with product images and buttons."""
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

    # Add inline Shop button when relevant
    inline = shop_inline_button() if response.show_shop_button else None

    await message.answer(
        formatted_text,
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True),
        reply_markup=inline or main_keyboard(),
    )


@router.message(F.text == "🛒 Shop")
async def handle_shop_button(message: types.Message) -> None:
    """Handle Shop button press."""
    await message.answer(
        "🛒 Open the shop to browse products and place your order:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Open Shop", url=SHOP_URL)]
        ]),
    )


@router.message(F.text == "❌ Close")
async def handle_close_manager(message: types.Message) -> None:
    """Handle Close button — return to AI mode."""
    await disable_manager_mode(message.chat.id)
    await message.answer(
        "Чат с менеджером завершён. Вы снова общаетесь с AI-ассистентом.\n\n"
        "Manager chat closed. You're now back with the AI assistant.",
        reply_markup=main_keyboard(),
    )


@router.message(F.voice)
async def handle_voice(message: types.Message, bot: Bot) -> None:
    """Handle incoming voice messages."""
    # If in manager mode, don't process with AI
    if await is_manager_mode(message.chat.id):
        await refresh_manager_mode(message.chat.id)
        return  # Let CRM handle it

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
    # Manager request
    if is_manager_request(message.text) or message.text.strip() == "👤 Manager":
        await handle_manager_start(message)
        return

    # If in manager mode, don't process with AI — let CRM handle
    if await is_manager_mode(message.chat.id):
        await refresh_manager_mode(message.chat.id)
        return

    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    history = await get_history(message.chat.id)
    response = await get_agent_response(message.text, chat_history=history)

    await add_message(message.chat.id, "user", message.text)
    await add_message(message.chat.id, "assistant", response.text)

    await send_response(message, bot, response)


@router.message()
async def handle_other(message: types.Message) -> None:
    """Handle any other message type."""
    # If in manager mode, don't process
    if await is_manager_mode(message.chat.id):
        await refresh_manager_mode(message.chat.id)
        return

    await message.answer(
        "Please send a text or voice message and I'll help you find information.",
        reply_markup=main_keyboard(),
    )
