from firecrawl import FirecrawlApp

from app.config.settings import settings

firecrawl = FirecrawlApp(api_key=settings.firecrawl_api_key)
