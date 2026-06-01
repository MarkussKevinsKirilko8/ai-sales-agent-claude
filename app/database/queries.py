from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database.models import OptInAcknowledged, ScrapedPage, SeenUser
from app.database.session import async_session


async def mark_user_seen(telegram_user_id: int) -> bool:
    """Record that a user has pressed /start. Returns True ONLY the first time
    this user is inserted (atomic INSERT ... ON CONFLICT DO NOTHING), so a
    /start double-tap or repeat can never fire the new-user webhook twice.
    """
    async with async_session() as session:
        stmt = (
            pg_insert(SeenUser)
            .values(telegram_user_id=telegram_user_id)
            .on_conflict_do_nothing(index_elements=["telegram_user_id"])
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


async def get_all_products() -> list[ScrapedPage]:
    """Get all scraped products from the database."""
    async with async_session() as session:
        result = await session.execute(
            select(ScrapedPage).order_by(ScrapedPage.source, ScrapedPage.title)
        )
        return list(result.scalars().all())


async def search_products(query: str) -> list[ScrapedPage]:
    """Search products by matching query against title and content."""
    async with async_session() as session:
        result = await session.execute(
            select(ScrapedPage).where(
                ScrapedPage.title.ilike(f"%{query}%")
                | ScrapedPage.content.ilike(f"%{query}%")
            )
        )
        return list(result.scalars().all())


async def search_products_exact(keywords: list[str]) -> list[ScrapedPage]:
    """Search products where ALL keywords match the title."""
    async with async_session() as session:
        conditions = [ScrapedPage.title.ilike(f"%{kw}%") for kw in keywords if len(kw) > 2]
        if not conditions:
            return []
        result = await session.execute(
            select(ScrapedPage).where(and_(*conditions))
        )
        return list(result.scalars().all())
