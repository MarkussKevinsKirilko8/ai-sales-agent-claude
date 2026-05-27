from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class SeenUser(Base):
    """Tracks users who have pressed /start at least once.

    Used to fire the "new user joined" webhook only on the user's FIRST ever
    /start. Lives in Postgres (named volume) so it survives redeploys.
    """
    __tablename__ = "seen_users"

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
