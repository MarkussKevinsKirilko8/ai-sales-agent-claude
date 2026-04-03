import logging

from sqlalchemy import delete, func, select

from app.database.models import ScrapedPage
from app.database.session import async_session
from app.scrapers.hilmabiocare import HilmaBiocareScraper
from app.scrapers.hilmabiocareshop import HilmaBiocareShopScraper

logger = logging.getLogger(__name__)


async def has_data() -> bool:
    """Check if we already have scraped products in the database."""
    async with async_session() as session:
        result = await session.execute(select(func.count()).select_from(ScrapedPage))
        count = result.scalar()
        return count > 0


async def run_scrapers(force: bool = False):
    """Run all scrapers and store results in the database.

    Args:
        force: If True, scrape even if data already exists.
    """
    if not force and await has_data():
        logger.info("Database already has product data — skipping scrape. Use POST /scrape to force.")
        return 0

    all_products = []

    # Scrape hilmabiocare.com
    logger.info("Starting hilmabiocare.com scraper...")
    scraper1 = HilmaBiocareScraper()
    products1 = await scraper1.scrape_all()
    all_products.extend(products1)
    logger.info(f"hilmabiocare.com: {len(products1)} products scraped")

    # Scrape hilmabiocareshop.com
    logger.info("Starting hilmabiocareshop.com scraper...")
    scraper2 = HilmaBiocareShopScraper()
    products2 = await scraper2.scrape_all()
    all_products.extend(products2)
    logger.info(f"hilmabiocareshop.com: {len(products2)} products scraped")

    # Store in database
    async with async_session() as session:
        # Clear old data
        await session.execute(delete(ScrapedPage))

        # Insert new data
        for product in all_products:
            page = ScrapedPage(**product)
            session.add(page)

        await session.commit()
        logger.info(f"Stored {len(all_products)} products in database")

    return len(all_products)
