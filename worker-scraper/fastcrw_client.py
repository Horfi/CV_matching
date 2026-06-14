import httpx
from config import FIRECRAWL_API_URL

def scrape_url_markdown(url: str) -> str:
    """
    Sends a POST request to fastCRW's Firecrawl-compatible /v1/scrape endpoint
    requesting the page in markdown format.
    """
    endpoint = f"{FIRECRAWL_API_URL}/v1/scrape"
    payload = {
        "url": url,
        "formats": ["markdown"]
    }
    
    # We timeout at 60 seconds since crawling/rendering can take a while
    response = httpx.post(endpoint, json=payload, timeout=60.0)
    if response.status_code != 200:
        import logging
        logging.getLogger(__name__).error("fastCRW error response: %s - %s", response.status_code, response.text)
    response.raise_for_status()
    
    result = response.json()
    if not result.get("success"):
        raise RuntimeError(f"fastCRW failed: {result.get('error', 'Unknown error')}")
        
    return result.get("data", {}).get("markdown", "")
