import os

REDIS_URL = os.getenv("REDIS_URL", "redis://message-broker:6379/0")
FIRECRAWL_API_URL = os.getenv("FIRECRAWL_API_URL", "http://fastcrw:3000")
