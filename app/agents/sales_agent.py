import json
import logging
from dataclasses import dataclass, field

import anthropic
import httpx

from app.config.settings import settings
from app.database.queries import search_products, search_products_exact

logger = logging.getLogger(__name__)

client = anthropic.AsyncAnthropic(api_key=settings.claude_api_key) if settings.claude_api_key else None


async def _call_ollama(system: str, messages: list[dict], max_tokens: int = 256,
                       format: str | None = None) -> str:
    """Call Ollama API using /api/chat for better KV cache reuse."""
    chat_messages = [{"role": "system", "content": system}]
    for msg in messages:
        chat_messages.append({"role": msg["role"], "content": msg["content"]})

    body = {
        "model": settings.ollama_model,
        "messages": chat_messages,
        "stream": False,
        "think": False,
        "keep_alive": -1,
        "options": {
            "num_predict": max_tokens,
            "num_ctx": 8192,
            "temperature": 0.3,
        },
    }
    if format:
        body["format"] = format

    async with httpx.AsyncClient(timeout=120.0) as http:
        response = await http.post(
            f"{settings.ollama_url}/api/chat",
            json=body,
        )
        response.raise_for_status()
        return response.json().get("message", {}).get("content", "")


async def _call_anthropic(system: str, messages: list[dict], model: str = "claude-sonnet-4-20250514", max_tokens: int = 1024) -> str:
    """Call Anthropic API."""
    response = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    )
    return response.content[0].text


async def call_llm(system: str, messages: list[dict], model: str = "claude-sonnet-4-20250514",
                    max_tokens: int = 1024, format: str | None = None) -> str:
    """Call the configured LLM provider. Haiku always routes to Anthropic."""
    # Haiku extraction always goes to Anthropic (cheap, fast, reliable JSON)
    if settings.llm_provider == "ollama":
        return await _call_ollama(system, messages, max_tokens, format)
    return await _call_anthropic(system, messages, model, max_tokens)

SYSTEM_PROMPT = """You are a sales support assistant for products in this online shop. Your goal is to help customers find products, answer questions, and guide them toward placing an order.

ABSOLUTE RULES — NEVER BREAK THESE:
1. NEVER invent, generate, or mention ANY URLs, links, website addresses, Telegram channels, or social media accounts. You do NOT know any links except what is in the product data provided to you. If you don't have a link — don't make one up. Just say "нажмите кнопку Магазин" or "обратитесь к менеджеру."
2. NEVER answer questions unrelated to products in this shop (politics, general knowledge, weather, etc.). If asked, respond: "Я помогаю по вопросам продукции в нашем магазине. Если у вас есть вопросы о товарах, наличии или заказе — буду рад помочь."
3. NEVER mention specific brand names in your identity. You are "assistant of this shop", not "assistant of Hilma Biocare" or any other brand.

LANGUAGE RULES:
- ALWAYS respond in the same language the user writes in (Russian, English, Latvian, etc.)

MULTI-QUESTION HANDLING:
- If the user asks multiple questions in one message, answer ALL of them. Do not skip any.
- Address each question separately if needed.

RESPONSE STYLE — CRITICAL (STRICT):
When asked about a specific product (including "расскажи про", "есть", "покажи", "tell me about"), your response MUST be EXACTLY this format:

[Product name English] / [Product name Russian]
Бренд: [brand]
Дозировка: [dosage]
Цена: [price] (or "Уточняется" if not available)
🟢 В наличии / 🟡 Ожидается
Для заказа нажмите кнопку Магазин.

STRICT RULES:
- The product name appears EXACTLY ONCE on the first line. Never repeat it.
- Do NOT copy the product name from the data if it would cause duplication.
- MAXIMUM 6 lines. No more.
- NO descriptions, NO effects, NO "Описание:", NO "Основные эффекты:", NO "Особенности:"
- NO usage instructions, NO side effects, NO comparisons
- NO emoji except 🟢 or 🟡

Only show detailed info (effects, description, features) if the user EXPLICITLY says "подробнее", "для чего", "какие эффекты", "what does it do".

STOCK STATUS:
- 🟢 = in stock
- 🟡 = out of stock / waiting for restock

AMBIGUOUS PRODUCT QUERIES:
When a user uses a slang/short name that could mean multiple products, ASK FOR CLARIFICATION:
- "дека" → "Вы имеете в виду Нандролон Деканоат или Тестостерон Ундеканоат?"
- "тесто/тест" → "Какой именно тестостерон? Энантат, ципионат, пропионат, ундеканоат или сустанон?"
- "трен/трэн/треник" → "Какой именно? Тренболон Ацетат, Энантат, Микс или Параболан?"
- "маст/мастер" → "Какой именно мастерон? Пропионат или Энантат?"

SLANG → PRODUCT MAPPING (single product, no clarification needed):
- "метан/меташка" → Methandienone
- "болд/болдик" → Boldenone Undecylenate
- "винни" → Stanozolol (tabs or injection — clarify which)
- "прови/провик" → Mesterolone
- "окси" → Oxymetholone
- "анавар" → Oxandrolone
- "суст" → Sustanon
- "гормонка/гр" → HGH (clarify: Liquid, Powder, or PEN?)
- "клен" → Clenbuterol
- "турик" → Turinabol
- "примка/прима" → Primobolan (clarify: tabs or injection?)
- "гало" → Halotestin

REVIEWS:
- When asked about reviews ("отзывы", "reviews"): "Отзывы можно посмотреть в нашем магазине на странице каждого товара. Нажмите кнопку Магазин."
- NEVER mention any Telegram channels, Instagram pages, or external review sites. You don't know them.

AVAILABILITY:
- In stock 🟢: show product info + guide to Shop
- Out of stock 🟡: suggest alternatives from the same category
- Restock: "Наличие регулярно пополняется, обычно от 2 недель до месяца."

PRICING:
- Price list: "Нажмите кнопку Магазин для просмотра цен."
- Shop doesn't load: "Попробуйте включить VPN."

DISCOUNTS:
When user asks about discounts ("скидка", "discount", "можно скидку"):
- Do NOT show any product info. Just ask about the order amount.
1. Ask ONLY: "На какую сумму вы планируете сделать заказ?"
2. Under 20,000 RUB: "Периодически у нас бывают акции, к сожалению в данный момент ничего не проводим."
3. 20,000 RUB or more: respond with EXACTLY: "MANAGER_TRANSFER: Дождитесь ответа менеджера — будет быстрее, если вы пришлёте список товаров и количество." (The MANAGER_TRANSFER prefix triggers automatic manager handoff.)

PAYMENT:
- Russian bank card: minimum 10,000 RUB
- Cryptocurrency: any amount

DELIVERY — list ONLY what IS available:
- Russia only
- Почта России: 1,200 RUB
- EMS Курьер: 3,000 RUB
- Tracking: 5-10 days for tracking code, then 3-7 days delivery
- Do NOT mention SDEK, warehouses, or ask "what method do you prefer?"

ORDERING PROBLEMS:
- Can't order: transfer to manager
- Can't open shop: "Попробуйте включить VPN. Если не получается — напишите 'менеджер'."

PRODUCT QUESTIONS:
- "Как ставить?" / "How to use?" → "Мы не даём рекомендаций по применению — всё индивидуально. Рекомендуем консультироваться со специалистами."
- NEVER provide medical advice, dosing, or cycle recommendations

MANAGER HANDOFF:
- Trigger: "менеджер", "manager", or asks for a human
- Response time: up to 24 hours
- Working hours: Mon-Fri 09:00-18:00 Moscow time

Below is the product catalog data you have access to:
"""

EXTRACT_PROMPT = """Extract the product name(s) from this user message. The user is asking about pharmaceutical/supplement products.

Return a JSON object with:
- "products": list of product names mentioned (just the product names, no extra words)
- "is_specific": true if the user is asking about ONE specific product, false if asking about multiple products or a general question
- "wants_manager": true if the user wants to speak with a human manager/operator/support person, false otherwise

Examples:
- "Tell me about Testosterone Enanthate" → {"products": ["Testosterone Enanthate"], "is_specific": true, "wants_manager": false}
- "What testosterone products do you have?" → {"products": ["Testosterone"], "is_specific": false, "wants_manager": false}
- "менеджер" → {"products": [], "is_specific": false, "wants_manager": true}
- "manager" → {"products": [], "is_specific": false, "wants_manager": true}
- "can I talk to a person?" → {"products": [], "is_specific": false, "wants_manager": true}
- "хочу поговорить с оператором" → {"products": [], "is_specific": false, "wants_manager": true}
- "menager please" → {"products": [], "is_specific": false, "wants_manager": true}
- "переведи на менеджера" → {"products": [], "is_specific": false, "wants_manager": true}
- "Hi, what can you help me with?" → {"products": [], "is_specific": false, "wants_manager": false}

Return ONLY the JSON, nothing else."""

MAX_CONTENT_LENGTH = 400  # Enough for name, brand, dosage, price, description


@dataclass
class AgentResponse:
    text: str
    product_images: list[dict] = field(default_factory=list)
    show_shop_button: bool = False
    wants_manager: bool = False
    is_error: bool = False


async def extract_product_names(user_message: str, chat_history: list[dict] = None) -> tuple[list[str], bool, bool]:
    """Use Claude Haiku to extract product names, intent, and manager request.
    Returns (products, is_specific, wants_manager).
    """
    try:
        # Include recent history so Haiku understands follow-up questions
        context = ""
        if chat_history:
            recent = chat_history[-4:]  # Last 2 exchanges
            history_lines = []
            for msg in recent:
                role = "User" if msg["role"] == "user" else "Assistant"
                content = msg["content"][:500] if msg["role"] == "assistant" else msg["content"]
                history_lines.append(f"{role}: {content}")
            context = "Recent conversation:\n" + "\n".join(history_lines) + "\n\n"

        raw_response = await call_llm(
            system="",
            messages=[
                {"role": "user", "content": f"{EXTRACT_PROMPT}\n\n{context}User message: {user_message}"}
            ],
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
        )

        raw = raw_response.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            raw = raw.rsplit("```", 1)[0]
            raw = raw.strip()

        result = json.loads(raw)
        logger.info(f"Extracted: {result}")
        return (
            result.get("products", []),
            result.get("is_specific", False),
            result.get("wants_manager", False),
        )
    except Exception as e:
        logger.error(f"Product extraction failed: {e}")
        words = [w for w in user_message.lower().split() if len(w) > 3]
        return words, False, False


async def find_relevant_products(user_message: str, chat_history: list[dict] = None) -> tuple[list, bool, bool]:
    """Find products relevant to the user's query using Claude for understanding.
    Returns (products, is_specific, wants_manager).
    """
    product_names, is_specific, wants_manager = await extract_product_names(user_message, chat_history)

    if wants_manager:
        return [], False, True

    if not product_names:
        return [], False, False

    # Search for each product name
    all_results = []
    for name in product_names:
        # Try exact match on the full product name
        keywords = name.lower().split()
        exact = await search_products_exact(keywords)
        if exact:
            all_results.extend(exact)
        else:
            # Fall back to broad search
            results = await search_products(name)
            all_results.extend(results)

    # Deduplicate by URL
    seen_urls = set()
    unique_products = []
    for product in all_results:
        if product.url not in seen_urls:
            seen_urls.add(product.url)
            unique_products.append(product)

    # Show images/treat as specific only if query unambiguously matches exactly 1 product
    # (2+ matches = ambiguous → let Claude ask for clarification, no images)
    if len(unique_products) != 1:
        is_specific = False

    return unique_products, is_specific, False


async def build_product_context(user_message: str, chat_history: list[dict] = None) -> tuple[str, list[dict], bool]:
    """Build context string and return matched product images.
    Returns (context, images, wants_manager).
    """
    unique_products, is_specific, wants_manager = await find_relevant_products(user_message, chat_history)

    if wants_manager:
        return "", [], True

    # Only show images for specific product queries (1-2 results)
    product_images = []
    if is_specific:
        for product in unique_products:
            if product.image_url:
                product_images.append({
                    "title": product.title.replace(" | Hilma Biocare Website", ""),
                    "image_url": product.image_url,
                    "url": product.url,
                })

    # If no relevant products found, don't dump full catalog — let LLM ask for clarification
    if not unique_products:
        return "\n[No specific product identified in the query. Ask the user to clarify which product they mean.]", [], False

    # Send detailed info for relevant products (max 3 to reduce prefill time)
    products_to_send = unique_products[:3]
    context_parts = []
    for product in products_to_send:
        content = product.content
        if len(content) > MAX_CONTENT_LENGTH:
            content = content[:MAX_CONTENT_LENGTH] + "..."

        context_parts.append(
            f"--- Product from {product.source} ---\n"
            f"URL: {product.url}\n"
            f"{content}\n"
        )

    return "\n".join(context_parts), product_images, False


async def get_agent_response(user_message: str, chat_history: list[dict] = None) -> AgentResponse:
    """Get a response from the Claude agent for a user message."""
    try:
        product_context, product_images, wants_manager = await build_product_context(user_message, chat_history)

        if wants_manager:
            return AgentResponse(text="", wants_manager=True)

        system = SYSTEM_PROMPT + product_context

        # Build messages with conversation history
        messages = []
        if chat_history:
            messages.extend(chat_history)
        messages.append({"role": "user", "content": user_message})

        response_text = await call_llm(
            system=system,
            messages=messages,
            max_tokens=512,  # enough for 6-line format + multi-question + discount flow
        )

        # Show Shop button when response mentions products, ordering, or shop
        shop_keywords = ["shop", "Shop", "корзин", "магазин", "оформ", "заказ", "купить", "наличи", "цен", "price", "order", "available"]
        show_shop = any(kw in response_text for kw in shop_keywords) or bool(product_images)

        return AgentResponse(
            text=response_text,
            product_images=product_images,
            show_shop_button=show_shop,
        )

    except Exception as e:
        logger.error(f"LLM API error: {e}")
        return AgentResponse(
            text="Произошла ошибка при обработке запроса. Пожалуйста, попробуйте ещё раз.",
            is_error=True,
        )
