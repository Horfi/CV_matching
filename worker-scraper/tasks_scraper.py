import logging
import re
import html
from urllib.parse import urlparse
import httpx
from celery_app import app
from fastcrw_client import scrape_url_markdown

logger = logging.getLogger(__name__)

def is_workday_url(url: str) -> bool:
    return "myworkdayjobs.com" in url

def scrape_workday_listing_via_api(url: str) -> str:
    parsed = urlparse(url)
    domain = parsed.netloc
    path = parsed.path.strip('/')
    segments = [s for s in path.split('/') if s]
    site_name = segments[0] if segments else ""
    
    domain_parts = domain.split('.')
    tenant = domain_parts[0]
    
    api_url = f"https://{domain}/wday/cxs/{tenant}/{site_name}/jobs"
    payload = {
        "appliedFacets": {},
        "limit": 20,
        "offset": 0,
        "searchText": ""
    }
    
    response = httpx.post(api_url, json=payload, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }, timeout=20.0)
    
    if response.status_code != 200:
        raise RuntimeError(f"Workday API request failed: {response.status_code} - {response.text}")
        
    data = response.json()
    job_postings = data.get("jobPostings", [])
    
    md_lines = ["# Workday Job Listing\n"]
    for job in job_postings:
        title = job.get("title", "Unknown Job")
        external_path = job.get("externalPath", "")
        if external_path.startswith('/'):
            rel_path = f"/{site_name}{external_path}"
        else:
            rel_path = f"/{site_name}/{external_path}"
        md_lines.append(f"- [{title}]({rel_path})")
        
    return "\n".join(md_lines)

def scrape_workday_detail_via_api(url: str) -> str:
    parsed = urlparse(url)
    domain = parsed.netloc
    path = parsed.path.strip('/')
    
    segments = [s for s in path.split('/') if s]
    try:
        job_idx = segments.index('job')
        site_name = segments[job_idx - 1]
    except (ValueError, IndexError):
        raise ValueError(f"Could not identify Workday structure in path: {path}")
        
    job_path = "/".join(segments[job_idx:])
    domain_parts = domain.split('.')
    tenant = domain_parts[0]
    
    api_url = f"https://{domain}/wday/cxs/{tenant}/{site_name}/{job_path}"
    
    response = httpx.get(api_url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json"
    }, timeout=20.0)
    
    if response.status_code != 200:
        raise RuntimeError(f"Workday detail API request failed: {response.status_code} - {response.text}")
        
    data = response.json()
    job_info = data.get("jobPostingInfo", {})
    title = job_info.get("title", "Unknown Job")
    desc_html = job_info.get("jobDescription", "")
    
    desc_text = desc_html.replace("<br>", "\n").replace("<br/>", "\n").replace("</p>", "\n\n").replace("</div>", "\n")
    desc_text = re.sub(r'<[^>]+>', '', desc_text)
    desc_text = html.unescape(desc_text)
    
    return f"# {title}\n\n{desc_text}"


@app.task(name='tasks_scraper.scrape_listing', queue='scraper')
def scrape_listing(source_id: int, url: str):
    """
    Crawls a Careers listing board URL to get raw page markdown, then delegates parsing
    to worker-data-io using Gemini.
    """
    logger.info("Scraping listing for source_id %s: %s", source_id, url)
    try:
        if is_workday_url(url):
            markdown = scrape_workday_listing_via_api(url)
        else:
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
        if is_workday_url(job_url):
            markdown = scrape_workday_detail_via_api(job_url)
        else:
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
