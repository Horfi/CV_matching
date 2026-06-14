from celery import Celery
from config import REDIS_URL

app = Celery('tasks_scraper', broker=REDIS_URL, backend=REDIS_URL)

# Import tasks to ensure they register
import tasks_scraper
