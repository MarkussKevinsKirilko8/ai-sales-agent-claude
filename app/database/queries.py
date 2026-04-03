from sqlalchemy import and_, select

from app.database.models import ScrapedPage
from app.database.session import async_session


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
