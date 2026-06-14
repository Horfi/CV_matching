import os

REDIS_URL = os.getenv("REDIS_URL", "redis://message-broker:6379/0")
QDRANT_URL = os.getenv("QDRANT_URL", "http://vector-store:6333")
DB_URI = os.getenv("DATABASE_URL", "postgresql://user:password@state-vault:5432/cv_state")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
