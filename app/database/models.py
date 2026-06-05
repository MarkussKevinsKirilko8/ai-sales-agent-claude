from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Integer, String, Text
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
    __tablename__ = "scraped_pages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(50), nullable=False)  # "hilmabiocare" or "hilmabiocareshop"
    url = Column(String(500), unique=True, nullable=False)
    title = Column(String(500))
    content = Column(Text)
    image_url = Column(String(500))
    page_type = Column(String(50))  # "product", "category", "info", etc.
    scraped_at = Column(DateTime, default=datetime.utcnow)
