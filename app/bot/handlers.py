import io
import logging

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
from app.services.i18n import detect_language, get_strings
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


def action_buttons(strings: dict, shop_url: str = SHOP_URL) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=strings["shop"], web_app=WebAppInfo(url=shop_url)),
            InlineKeyboardButton(text=strings["manager"], callback_data="request_manager"),
        ]
    ])


def close_button(strings: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=strings["close"], callback_data="close_manager")]
    ])


async def get_user_lang(chat_id: int, current_text: str = "") -> str:
    """Get the user's preferred language. Detects from current text or recent history."""
    if current_text:
        return await detect_language(current_text)

    history = await get_history(chat_id)
    if history:
        last_user = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")
        if last_user:
            return await detect_language(last_user)

    return "Russian"


async def summarize_conversation(history: list[dict], lang: str = "Russian") -> str:
    if not history:
        return "Новый клиент, без истории переписки."

    conversation = "\n".join(
        f"{'User' if m['role'] == 'user' else 'Bot'}: {m['content'][:300]}"
        for m in history[-8:]
    )

    try:
        from app.agents.sales_agent import call_llm
        response_text = await call_llm(
            system="",
            messages=[{
                "role": "user",
                "content": (
                    f"Summarize this customer conversation in 2-3 sentences in {lang}. "
                    "Focus on: what product(s) the customer is interested in, what they need help with, "
                    "and any important details. Be concise.\n\n"
                    f"Conversation:\n{conversation}"
                ),
            }],
            max_tokens=300,
        )
        return response_text
    except Exception as e:
        logger.error(f"Summary generation failed: {e}")
        return "Не удалось создать сводку."


async def handle_manager_start(message: types.Message, bot: Bot, lang: str = "Russian"):
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

    strings = await get_strings(lang)
    await message.answer(
        strings["manager_connect"],
        reply_markup=close_button(strings),
    )


ERROR_CAT_PATH = "/app/app/assets/error_cat.png"


async def send_response(
    message: types.Message,
    bot: Bot,
    response: AgentResponse,
    lang: str = "Russian",
) -> None:
    # Send sad cat on error
    if response.is_error:
        try:
            from aiogram.types import FSInputFile
            photo = FSInputFile(ERROR_CAT_PATH)
            await bot.send_photo(
                chat_id=message.chat.id,
                photo=photo,
                caption=response.text,
            )
        except Exception:
            await message.answer(response.text)
        return

    formatted_text = markdown_to_telegram_html(response.text)

    if response.product_images:
        for product in response.product_images[:3]:
            try:
                await bot.send_photo(
                    chat_id=message.chat.id,
                    photo=product["image_url"],
                )
            except Exception:
                pass

    strings = await get_strings(lang)

    # If exactly 1 specific product, link Shop button directly to its page
    shop_url = SHOP_URL
    if response.product_images and len(response.product_images) == 1:
        product_url = response.product_images[0].get("url")
        if product_url:
            shop_url = product_url

    await message.answer(
        formatted_text,
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True),
        reply_markup=action_buttons(strings, shop_url=shop_url),
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

    strings = await get_strings("Russian")
    await message.answer(
        strings["welcome"],
        parse_mode="HTML",
        reply_markup=action_buttons(strings),
    )


@router.message(Command("close"))
async def handle_close_command(message: types.Message) -> None:
    if message.chat.type in ("group", "supergroup"):
        return

    # Don't detect from "/close" text — use chat history to determine language
    lang = await get_user_lang(message.chat.id)
    strings = await get_strings(lang)

    if await is_manager_mode(message.chat.id):
        await disable_manager_mode(message.chat.id)
        await message.answer(
            strings["manager_closed"],
            reply_markup=action_buttons(strings),
        )
    else:
        await message.answer(strings["already_ai"])


@router.callback_query(F.data == "request_manager")
async def handle_manager_callback(callback: types.CallbackQuery, bot: Bot) -> None:
    lang = await get_user_lang(callback.message.chat.id)
    strings = await get_strings(lang)

    if await is_manager_mode(callback.message.chat.id):
        await callback.answer(strings["manager_already"])
        return
    await callback.answer()

    await handle_manager_start(callback.message, bot, lang)


@router.callback_query(F.data == "close_manager")
async def handle_close_manager(callback: types.CallbackQuery) -> None:
    await disable_manager_mode(callback.message.chat.id)
    await callback.answer()

    lang = await get_user_lang(callback.message.chat.id)
    strings = await get_strings(lang)

    await callback.message.edit_text(strings["manager_closed"])
    await callback.message.answer(
        strings["manager_closed"],
        reply_markup=action_buttons(strings),
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
        strings = await get_strings("Russian")
        await message.answer(strings["voice_fail"], reply_markup=action_buttons(strings))
        return

    lang = await detect_language(text)

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
        msg_count = await refresh_manager_mode(message.chat.id)
        # Send reassurance on first message in manager mode
        if msg_count == 1:
            lang = await get_user_lang(message.chat.id, message.text)
            strings = await get_strings(lang)
            await message.answer(
                strings.get("manager_waiting",
                    "Ваше сообщение передано менеджеру. Ожидайте ответа в течение 24 часов. "
                    "Напишите /close чтобы вернуться к AI-ассистенту."
                ),
            )
        return

    lang = await detect_language(message.text)

    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    history = await get_history(message.chat.id)
    response = await get_agent_response(message.text, chat_history=history)

    if response.wants_manager:
        await handle_manager_start(message, bot, lang)
        return

    # Check if LLM response triggers manager transfer (discount over 20K)
    if "MANAGER_TRANSFER:" in response.text:
        response.text = response.text.replace("MANAGER_TRANSFER: ", "").replace("MANAGER_TRANSFER:", "")
        await message.answer(response.text)
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

    strings = await get_strings("Russian")
    await message.answer(strings["other"], reply_markup=action_buttons(strings))
