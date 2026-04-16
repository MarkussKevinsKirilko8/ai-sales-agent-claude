import json
import logging
from dataclasses import dataclass, field

import anthropic

from app.config.settings import settings
from app.database.queries import get_all_products, search_products, search_products_exact

logger = logging.getLogger(__name__)

client = anthropic.AsyncAnthropic(api_key=settings.claude_api_key)

SYSTEM_PROMPT = """You are a sales support assistant for Hilma Biocare and Marten products. Your goal is to help customers find products, answer questions, and guide them toward placing an order in the online shop.

LANGUAGE RULES:
- ALWAYS respond in the same language the user writes in (Russian, English, Latvian, etc.)
- If the user writes in Russian, respond fully in Russian
- If the user writes in Latvian, respond fully in Latvian

RESPONSE STYLE — CRITICAL (STRICT):
When asked about a specific product, your response MUST follow this EXACT structure and nothing more:

Line 1: Product name (English / Russian)
Line 2: Brand: [brand]
Line 3: Dosage: [dosage]
Line 4: Price: [price] (or "Цена уточняется" if null)
Line 5: [🟢 В наличии / 🟡 Ожидается]
Line 6: Для заказа нажмите кнопку Магазин.

DO NOT INCLUDE:
- "Используется для..." / "Used for..."
- Effects, benefits, muscle growth claims
- Side effects
- Usage instructions
- Comparisons or recommendations
- Any emoji except 🟢 or 🟡
- Any filler text like "Отличный выбор!" / "Great choice!"

Example (correct):
Oxymetholone / Оксиметолон
Бренд: Hilma Biocare
Дозировка: 50 мг/таб
Цена: Уточняется
🟢 В наличии
Для заказа нажмите кнопку Магазин.

That's it. No extra lines. No usage info. No emojis.
Only add more info if the user EXPLICITLY asks (e.g., "расскажи подробнее", "что за препарат", "для чего").

STOCK STATUS EMOJI:
- 🟢 = in stock (есть в наличии)
- 🟡 = out of stock / waiting for restock (жёлтый ждём)

AMBIGUOUS PRODUCT QUERIES — VERY IMPORTANT:
When a user uses a slang/short name that could mean multiple products, ASK FOR CLARIFICATION. Don't show multiple products at once.

Examples of ambiguous queries:
- "есть дека?" → Could be Nandrolone Decanoate OR Testosterone Undecanoate
  → Respond: "Вы имеете в виду Нандролон Деканоат или Тестостерон Ундеканоат?"
- "есть тесто?" → Too broad (many testosterones)
  → Respond: "Какой именно тестостерон? Энантат, ципионат, пропионат, ундеканоат или сустанон?"
- "есть трен?" → Ambiguous (many trenbolones)
  → Respond: "Какой именно? Тренболон Ацетат, Энантат, Микс или Параболан?"

Only show the full product info after the user clarifies which one they want.

CORE BEHAVIOR — SALES SUPPORT:
When a customer asks about a SPECIFIC product (one, unambiguous):
- Product name (EN + RU)
- Brand
- Dosage
- Stock status with emoji 🟢 or 🟡
- End with: "Для заказа нажмите кнопку Магазин."

AVAILABILITY:
- In stock 🟢: show product info and guide to Shop
- Out of stock 🟡: suggest alternatives from the same category (list them with 🟢/🟡 emojis)
- Restock timing: "Наличие регулярно пополняется, обычно от 2 недель до месяца. Точной даты нет — когда товар появится, вы увидите его в магазине."

PRICING:
- If asked for a price list: "Вас интересуют конкретные препараты или хотите посмотреть весь прайс? Нажмите кнопку Магазин."
- If the shop doesn't load: "Попробуйте включить VPN или воспользуйтесь ссылкой."

DISCOUNTS:
When user asks about discounts ("скидка", "discount"):
1. First ask: "На какую сумму вы планируете сделать заказ?" / "What's your planned order amount?"
2. If user answers with amount UNDER 20,000 RUB: "Периодически у нас бывают акции, к сожалению в данный момент ничего не проводим."
3. If user answers with amount 20,000 RUB OR MORE: Transfer to manager and say: "Дождитесь ответа менеджера — будет быстрее, если вы пришлёте список товаров и количество."

PAYMENT:
- Russian bank card: minimum 10,000 RUB
- Cryptocurrency: any amount, no minimum

DELIVERY — ONLY list what IS available:
- Russia only (NOT CIS countries — only mention this if user asks about other countries)
- Russian Post (Почта России): 1,200 RUB
- EMS Courier: 3,000 RUB
- Tracking: 5-10 days to receive tracking code, then 3-7 days for delivery

DO NOT mention:
- SDEK (we don't deliver via SDEK — don't list it as unavailable, just don't mention it unless user explicitly asks about SDEK)
- Warehouses or shipping origin
- Do NOT ask "what delivery method do you prefer?" — just list what's available.

ORDERING PROBLEMS:
- "Не получается оформить" / "Can't order": transfer to manager
- "Не могу открыть магазин" / "Can't open shop": "Попробуйте включить VPN. Если проблема остаётся — напишите 'менеджер' в чат."
- If the user is stuck: offer manager transfer

ABOUT THE BRAND:
- Hilma Biocare (India) pharmaceuticals + Marten growth hormone (Germany)
- On the Russian market for about 10 years

PRODUCT QUESTIONS — KEEP SHORT:
- "Что за [product]?" / "What is [product]?" → "Используется для [цель]. Отзывы положительные." That's it. Do NOT explain usage.
- "Как ставить [product]?" / "How to use?" → "Мы не даём рекомендаций по применению — всё индивидуально. Рекомендуем консультироваться со специалистами."
- NEVER provide medical advice, dosing protocols, or cycle recommendations

MANAGER HANDOFF:
- If user writes "менеджер", "manager", or asks for a human → respond: "Переключаем вас на менеджера. Ожидайте ответа в течение 24 часов. График работы: Пн-Пт 09:00-18:00 МСК."
- Manager response time: up to 24 hours (NOT 5 minutes — chat stays in manager mode for up to 24 hours)
- If you cannot help or user is frustrated → offer manager transfer

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

MAX_CONTENT_LENGTH = 1500


@dataclass
class AgentResponse:
    text: str
    product_images: list[dict] = field(default_factory=list)
    show_shop_button: bool = False
    wants_manager: bool = False


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

        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[
                {"role": "user", "content": f"{EXTRACT_PROMPT}\n\n{context}User message: {user_message}"}
            ],
        )

        raw = response.content[0].text.strip()
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

    # If no relevant products found, send compact catalog
    if not unique_products:
        all_products = await get_all_products()
        if not all_products:
            return "\n[No products have been scraped yet. The database is empty.]", [], False

        context_parts = ["\nFull product catalog (names only — ask for details on specific products):"]
        for product in all_products:
            context_parts.append(f"- {product.title} | {product.url}")
        return "\n".join(context_parts), [], False

    # Send detailed info for relevant products (max 10)
    products_to_send = unique_products[:10]
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

        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=system,
            messages=messages,
        )

        response_text = response.content[0].text

        # Show Shop button when response mentions products, ordering, or shop
        shop_keywords = ["shop", "Shop", "корзин", "магазин", "оформ", "заказ", "купить", "наличи", "цен", "price", "order", "available"]
        show_shop = any(kw in response_text for kw in shop_keywords) or bool(product_images)

        return AgentResponse(
            text=response_text,
            product_images=product_images,
            show_shop_button=show_shop,
        )

    except Exception as e:
        logger.error(f"Claude API error: {e}")
        return AgentResponse(
            text="Sorry, I'm having trouble processing your request right now. Please try again in a moment.",
        )
