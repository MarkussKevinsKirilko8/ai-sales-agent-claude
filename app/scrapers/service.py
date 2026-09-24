import logging

from sqlalchemy import delete, func, select

from app.database.models import ScrapedPage
from app.database.session import async_session
from app.scrapers.product_api import ProductAPIScraper
from app.services import bot_shops

# Firecrawl scrapers (kept as fallback, currently disabled)
# from app.scrapers.hilmabiocare import HilmaBiocareScraper
# from app.scrapers.hilmabiocareshop import HilmaBiocareShopScraper

logger = logging.getLogger(__name__)


async def has_data() -> bool:
    """Check if we already have scraped products in the database."""
    async with async_session() as session:
        result = await session.execute(select(func.count()).select_from(ScrapedPage))
        count = result.scalar()
        return count > 0


async def run_scrapers(force: bool = False):
    """Fetch every shop's catalog from the API and store per-shop.

    Each bot has its own shop (mini-app) with its own products, prices and
    currency — e.g. the Europe shop is in EUR. We scrape the default catalog
    plus every registered bot's shop, so each bot answers from its own data.

    A shop whose fetch fails keeps its previous rows (we only replace a shop's
    rows after a successful fetch), so one flaky shop can't blank the others.

    Args:
        force: If True, sync even if data already exists.
    """
    if not force and await has_data():
        logger.info("Database already has product data — skipping sync. Use POST /scrape to force.")
        return 0

    shops = bot_shops.all_catalog_shops()
    if not shops:
        logger.warning("No shop catalogs to scrape (registry empty and no default webshop_link)")
        return 0

    api_scraper = ProductAPIScraper()
    total = 0

    for shop in sorted(shops):
        products = await api_scraper.scrape_all(shop)
        if not products:
            logger.warning(f"Shop {shop}: fetch returned nothing — keeping its previous rows")
            continue

        async with async_session() as session:
            # Replace ONLY this shop's rows, and only after a successful fetch
            await session.execute(delete(ScrapedPage).where(ScrapedPage.shop == shop))
            for product in products:
                session.add(ScrapedPage(**product))
            await session.commit()

        logger.info(f"Shop {shop}: stored {len(products)} products")
        total += len(products)

    return total
