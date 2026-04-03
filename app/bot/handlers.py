import io

from aiogram import Bot, F, Router, types
from aiogram.enums import ChatAction
from aiogram.types import LinkPreviewOptions

from app.agents.sales_agent import AgentResponse, get_agent_response
from app.services.chat_history import add_message, get_history
from app.services.formatting import markdown_to_telegram_html
from app.services.voice import transcribe_voice

router = Router()


async def send_response(message: types.Message, bot: Bot, response: AgentResponse) -> None:
    """Send the agent response with product images paired with descriptions."""
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
    )


@router.message(F.voice)
async def handle_voice(message: types.Message, bot: Bot) -> None:
    """Handle incoming voice messages."""
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    file = await bot.get_file(message.voice.file_id)
    file_bytes = io.BytesIO()
    await bot.download_file(file.file_path, file_bytes)

    text = await transcribe_voice(file_bytes.getvalue())
    if not text:
        await message.answer("Sorry, I couldn't understand the voice message. Please try again or send a text message.")
        return

    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    # Get history and respond
    history = await get_history(message.chat.id)
    response = await get_agent_response(text, chat_history=history)

    # Save to history
    await add_message(message.chat.id, "user", text)
    await add_message(message.chat.id, "assistant", response.text)

    await message.answer(f"🎤 <i>{text}</i>")
    await send_response(message, bot, response)


@router.message(F.text)
async def handle_message(message: types.Message, bot: Bot) -> None:
    """Handle all incoming text messages."""
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    # Get history and respond
    history = await get_history(message.chat.id)
    response = await get_agent_response(message.text, chat_history=history)

    # Save to history
    await add_message(message.chat.id, "user", message.text)
    await add_message(message.chat.id, "assistant", response.text)

    await send_response(message, bot, response)


@router.message()
async def handle_other(message: types.Message) -> None:
    """Handle any other message type."""
    await message.answer("Please send a text or voice message and I'll help you find information.")
