import logging
from celery_app import app
from fastcrw_client import scrape_url_markdown

logger = logging.getLogger(__name__)

@app.task(name='tasks_scraper.scrape_listing', queue='scraper')
def scrape_listing(source_id: int, url: str):
    """
    Crawls a Careers listing board URL to get raw page markdown, then delegates parsing
    to worker-data-io using Gemini.
    """
    logger.info("Scraping listing for source_id %s: %s", source_id, url)
    try:
        markdown = scrape_url_markdown(url)
        
        # Pass the raw markdown back to worker-data-io for parsing and synchronization
        app.send_task(
            'tasks_api.parse_and_sync_listing',
            args=[source_id, markdown, url],
            queue='data_io'
        )
        return "Successfully crawled listing page. Enqueued Gemini parsing/sync task."
    except Exception as exc:
        logger.error("Failed to scrape listing: %s", exc)
        app.send_task(
            'tasks_api.update_source_status',
            args=[source_id, 'failed'],
            queue='data_io'
        )
        raise exc


@app.task(name='tasks_scraper.scrape_detail', queue='scraper')
def scrape_detail(source_id: int, job_url: str):
    """
    Crawls an individual job detail page to get raw page markdown, then delegates parsing
    to worker-data-io using Gemini.
    """
    logger.info("Scraping details for job: %s", job_url)
    try:
        markdown = scrape_url_markdown(job_url)
        
        # Send the raw markdown back to worker-data-io for parsing and saving
        app.send_task(
            'tasks_api.parse_and_save_job_detail',
            args=[source_id, job_url, markdown],
            queue='data_io'
        )
        return "Successfully crawled detail page. Enqueued Gemini parsing/save task."
    except Exception as exc:
        logger.error("Failed to scrape detail for %s: %s", job_url, exc)
        app.send_task(
            'tasks_api.update_source_status',
            args=[source_id, 'failed'],
            queue='data_io'
        )
        raise exc
