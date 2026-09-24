from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class BotSeenUser(Base):
    """Tracks the FIRST /start per (bot, user). Composite PK so the new-user
    notification webhook can fire once per (bot, user) — the daily digest
    on the notification service then pools by bot via bot_handle.

    Replaces the previous global seen_users table (which only had user_id and
    therefore couldn't distinguish bots). The old `seen_users` Postgres table
    is now orphaned and safe to drop manually if you want to clean up.
    """
    __tablename__ = "bot_seen_users"

    bot_id = Column(BigInteger, primary_key=True, autoincrement=False)
    telegram_user_id = Column(BigInteger, primary_key=True, autoincrement=False)
    first_seen = Column(DateTime, default=datetime.utcnow)


class OptInAcknowledged(Base):
    """Tracks the FIRST non-/start interaction per (bot, user) for opt-in bots.

    Separate from seen_users so opt-in bots' tracking is bot-scoped without
    changing the seen_users semantic the other bots rely on. Lives in Postgres
    so it survives redeploys (otherwise every user would re-see the prompt).
    """
    __tablename__ = "opt_in_acknowledged"

    bot_id = Column(BigInteger, primary_key=True, autoincrement=False)
    telegram_user_id = Column(BigInteger, primary_key=True, autoincrement=False)
    first_seen = Column(DateTime, default=datetime.utcnow)


class ScrapedPage(Base):
    """Per-shop product catalog.

    `shop` is the webshop_link host (e.g. "RoidTeam_shop_europe_bot.miniapp-rf.app")
    so each bot can search ONLY its own shop's products/prices. The same product
    code exists in several shops, hence the (shop, url) uniqueness instead of a
    globally-unique url.

    Table renamed from `scraped_pages` (which had no shop column and a unique
    url — create_all can't alter existing tables). The old `scraped_pages`
    Postgres table is orphaned and safe to drop manually.
    """
    __tablename__ = "shop_products"
    __table_args__ = (UniqueConstraint("shop", "url", name="uq_shop_products_shop_url"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    shop = Column(String(200), nullable=False, index=True)  # webshop_link host
    source = Column(String(50), nullable=False)  # "product_api"
    url = Column(String(500), nullable=False)
    title = Column(String(500))
    content = Column(Text)
    image_url = Column(String(500))
    page_type = Column(String(50))  # "product", "category", "info", etc.
    scraped_at = Column(DateTime, default=datetime.utcnow)
