from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database.models import BotSeenUser, OptInAcknowledged, ScrapedPage
from app.database.session import async_session


async def mark_user_seen(bot_id: int, telegram_user_id: int) -> bool:
    """Record a user's FIRST /start on a specific bot. Returns True only on
    the first insert per (bot_id, user_id) — atomic INSERT ON CONFLICT DO
    NOTHING, so a /start double-tap can never double-fire the webhook.

    Bot-scoped: the same user can be "new" on each bot independently, which
    is what the notification service's per-bot daily digest needs.
    """
    async with async_session() as session:
        stmt = (
            pg_insert(BotSeenUser)
            .values(bot_id=bot_id, telegram_user_id=telegram_user_id)
            .on_conflict_do_nothing(index_elements=["bot_id", "telegram_user_id"])
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount == 1


async def mark_opt_in_seen(bot_id: int, telegram_user_id: int) -> bool:
    """Record an opt-in bot's first non-/start interaction with a user. Returns
    True only on the first insert per (bot_id, user). Bot-scoped so the same
    user can be handled per bot independently.
    """
    async with async_session() as session:
        stmt = (
            pg_insert(OptInAcknowledged)
            .values(bot_id=bot_id, telegram_user_id=telegram_user_id)
            .on_conflict_do_nothing(index_elements=["bot_id", "telegram_user_id"])
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount == 1


async def get_all_products(shop: str | None = None) -> list[ScrapedPage]:
    """Get all scraped products, optionally scoped to one shop's catalog."""
    async with async_session() as session:
        stmt = select(ScrapedPage).order_by(ScrapedPage.source, ScrapedPage.title)
        if shop:
            stmt = stmt.where(ScrapedPage.shop == shop)
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def search_products(query: str, shop: str) -> list[ScrapedPage]:
    """Search ONE shop's catalog by matching query against title and content.
    Scoped by shop so every bot quotes its own products/prices/currency."""
    async with async_session() as session:
        result = await session.execute(
            select(ScrapedPage).where(
                ScrapedPage.shop == shop,
                ScrapedPage.title.ilike(f"%{query}%")
                | ScrapedPage.content.ilike(f"%{query}%"),
            )
        )
        return list(result.scalars().all())


async def search_products_exact(keywords: list[str], shop: str) -> list[ScrapedPage]:
    """Search ONE shop's catalog where ALL keywords match the title."""
    async with async_session() as session:
        conditions = [ScrapedPage.title.ilike(f"%{kw}%") for kw in keywords if len(kw) > 2]
        if not conditions:
            return []
        result = await session.execute(
            select(ScrapedPage).where(ScrapedPage.shop == shop, and_(*conditions))
        )
        return list(result.scalars().all())
