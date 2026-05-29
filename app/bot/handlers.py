import io
import logging

from aiogram import Bot, F, Router, types
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    WebAppInfo,
)

from app.agents.sales_agent import AgentResponse, get_agent_response
from app.database.queries import mark_user_seen
from app.services import bot_shops
from app.services.bot_start_webhook import schedule_bot_start_notification
from app.services.chat_history import add_message, get_history
from app.services.formatting import markdown_to_telegram_html
from app.services.i18n import detect_language, get_strings
from app.services.manager_mode import (
    enable_manager_mode,
    disable_manager_mode,
    is_manager_mode,
    refresh_manager_mode,
    save_manager_summary,
)
from app.services.voice import transcribe_voice

router = Router()
logger = logging.getLogger(__name__)

def resolve_shop_url(bot_id: int, product_rel_url: str | None = None) -> str | None:
    """The shop link for a given bot. None if the bot has no mini-app shop.
    A relative product deep link (`?page=...`) is appended to the bot's base.
    """
    base = bot_shops.shop_url_for_bot(bot_id)
    if not base:
        return None
    if product_rel_url and product_rel_url.startswith("?"):
        return base.rstrip("/") + "/" + product_rel_url
    return base


def action_buttons(strings: dict, shop_url: str | None = None, show_manager: bool = True) -> InlineKeyboardMarkup | None:
    """Shop button only when the bot has a shop URL; Manager button only when
    show_manager. Returns None if neither (Telegram rejects empty keyboards)."""
    row = []
    if shop_url:
        row.append(InlineKeyboardButton(text=strings["shop"], web_app=WebAppInfo(url=shop_url)))
    if show_manager:
        row.append(InlineKeyboardButton(text=strings["manager"], callback_data="request_manager"))
    if not row:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[row])


def main_keyboard(strings: dict, bot_id: int, product_rel: str | None = None) -> InlineKeyboardMarkup | None:
    """Per-bot main keyboard: shop URL + manager button gated by bot config."""
    return action_buttons(
        strings,
        shop_url=resolve_shop_url(bot_id, product_rel),
        show_manager=bot_shops.manager_enabled_for_bot(bot_id),
    )


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


async def handle_manager_start(message: types.Message, bot: Bot, lang: str = "Russian", user: types.User | None = None):
    await enable_manager_mode(bot.id, message.chat.id)

    history = await get_history(message.chat.id)
    summary = await summarize_conversation(history, lang)

    # When invoked from a callback (Менеджер button), message.from_user is the bot.
    # The caller must pass `user=callback.from_user` for the real customer identity.
    if user is None:
        user = message.from_user

    # Summary is consumed by the CRM via /api/manager-status (the old Telegram
    # manager group predates the CRM and is no longer used).
    await save_manager_summary(
        bot.id,
        message.chat.id,
        summary=summary,
        user_name=user.full_name or "",
        username=user.username or "",
    )

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

    # Link the Shop button to the specific product page when exactly 1 matched
    product_rel = None
    if response.product_images and len(response.product_images) == 1:
        product_rel = response.product_images[0].get("url")

    await message.answer(
        formatted_text,
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True),
        reply_markup=main_keyboard(strings, bot.id, product_rel),
    )


@router.message(CommandStart())
async def handle_start(message: types.Message, bot: Bot) -> None:
    if message.chat.type in ("group", "supergroup"):
        return

    # First-time gate runs BEFORE the reply (atomic; a double-tap can't double-fire)
    is_new_user = await mark_user_seen(message.from_user.id)

    # /start always resets state — exit manager mode if active
    if await is_manager_mode(bot.id, message.chat.id):
        await disable_manager_mode(bot.id, message.chat.id)

    strings = await get_strings("Russian")
    await message.answer(
        strings["welcome"],
        parse_mode="HTML",
        reply_markup=main_keyboard(strings, bot.id),
    )

    # Notify the fleet service in the background (only on the user's first /start)
    if is_new_user:
        schedule_bot_start_notification(message.from_user)


@router.message(Command("close"))
async def handle_close_command(message: types.Message, bot: Bot) -> None:
    if message.chat.type in ("group", "supergroup"):
        return

    # Don't detect from "/close" text — use chat history to determine language
    lang = await get_user_lang(message.chat.id)
    strings = await get_strings(lang)

    if await is_manager_mode(bot.id, message.chat.id):
        await disable_manager_mode(bot.id, message.chat.id)
        await message.answer(
            strings["manager_closed"],
            reply_markup=main_keyboard(strings, bot.id),
        )
    else:
        await message.answer(strings["already_ai"])


@router.callback_query(F.data == "request_manager")
async def handle_manager_callback(callback: types.CallbackQuery, bot: Bot) -> None:
    lang = await get_user_lang(callback.message.chat.id)
    strings = await get_strings(lang)

    if await is_manager_mode(bot.id, callback.message.chat.id):
        await callback.answer(strings["manager_already"])
        return
    await callback.answer()

    await handle_manager_start(callback.message, bot, lang, user=callback.from_user)


@router.callback_query(F.data == "close_manager")
async def handle_close_manager(callback: types.CallbackQuery, bot: Bot) -> None:
    await disable_manager_mode(bot.id, callback.message.chat.id)
    await callback.answer()

    lang = await get_user_lang(callback.message.chat.id)
    strings = await get_strings(lang)

    await callback.message.edit_text(strings["manager_closed"])
    await callback.message.answer(
        strings["manager_closed"],
        reply_markup=main_keyboard(strings, bot.id),
    )


@router.message(F.voice)
async def handle_voice(message: types.Message, bot: Bot) -> None:
    if message.chat.type in ("group", "supergroup"):
        return

    if await is_manager_mode(bot.id, message.chat.id):
        # In manager mode the bot stays silent; just keep the session alive.
        await refresh_manager_mode(bot.id, message.chat.id)
        return

    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    file = await bot.get_file(message.voice.file_id)
    file_bytes = io.BytesIO()
    await bot.download_file(file.file_path, file_bytes)

    text = await transcribe_voice(file_bytes.getvalue())
    if not text:
        strings = await get_strings("Russian")
        await message.answer(strings["voice_fail"], reply_markup=main_keyboard(strings, bot.id))
        return

    lang = await detect_language(text)

    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    history = await get_history(message.chat.id)
    response = await get_agent_response(text, chat_history=history)

    await add_message(message.chat.id, "user", text)
    await message.answer(f"🎤 <i>{text}</i>")

    if response.wants_manager:
        await handle_manager_start(message, bot, lang)
        return

    if "MANAGER_TRANSFER:" in response.text:
        response.text = response.text.replace("MANAGER_TRANSFER: ", "").replace("MANAGER_TRANSFER:", "")
        await message.answer(response.text)
        await handle_manager_start(message, bot, lang)
        return

    await add_message(message.chat.id, "assistant", response.text)
    await send_response(message, bot, response, lang)


@router.message(F.text)
async def handle_message(message: types.Message, bot: Bot) -> None:
    logger.info(f"Message from chat_id={message.chat.id}, type={message.chat.type}, bot={bot.id}")

    if message.chat.type in ("group", "supergroup"):
        return

    if await is_manager_mode(bot.id, message.chat.id):
        # In manager mode the bot stays silent; just keep the session alive.
        await refresh_manager_mode(bot.id, message.chat.id)
        return

    lang = await detect_language(message.text)

    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    history = await get_history(message.chat.id)
    response = await get_agent_response(message.text, chat_history=history)

    await add_message(message.chat.id, "user", message.text)

    if response.wants_manager:
        await handle_manager_start(message, bot, lang)
        return

    # Check if LLM response triggers manager transfer (discount over 20K)
    if "MANAGER_TRANSFER:" in response.text:
        response.text = response.text.replace("MANAGER_TRANSFER: ", "").replace("MANAGER_TRANSFER:", "")
        await message.answer(response.text)
        await handle_manager_start(message, bot, lang)
        return

    await add_message(message.chat.id, "assistant", response.text)
    await send_response(message, bot, response, lang)


@router.message()
async def handle_other(message: types.Message, bot: Bot) -> None:
    if message.chat.type in ("group", "supergroup"):
        return

    if await is_manager_mode(bot.id, message.chat.id):
        # In manager mode the bot stays silent; just keep the session alive.
        await refresh_manager_mode(bot.id, message.chat.id)
        return

    strings = await get_strings("Russian")
    await message.answer(strings["other"], reply_markup=main_keyboard(strings, bot.id))
