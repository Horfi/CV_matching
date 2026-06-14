import sys
import time
import httpx

ORCHESTRATOR_URL = "http://localhost:8001"

def test_scraping_flow():
    print("Connecting to workflow-orchestrator API...")
    
    # 1. Add career page source
    listing_payload = {
        "name": "Google Careers Results",
        "url": "https://www.google.com/about/careers/applications/jobs/results",
        "type": "careers_page"
    }
    r = httpx.post(f"{ORCHESTRATOR_URL}/api/v1/scraping/sources", json=listing_payload, timeout=10.0)
    assert r.status_code == 200, f"Failed to add listing source: {r.text}"
    listing_source = r.json()
    print("Added listing source:", listing_source)
    
    # 2. Add single job detail source
    detail_payload = {
        "name": "Staff Software Engineer Full Stack YouTube",
        "url": "https://www.google.com/about/careers/applications/jobs/results/136150424582267590-staff-software-engineer-full-stack-youtube",
        "type": "single_job"
    }
    r = httpx.post(f"{ORCHESTRATOR_URL}/api/v1/scraping/sources", json=detail_payload, timeout=10.0)
    assert r.status_code == 200, f"Failed to add detail source: {r.text}"
    detail_source = r.json()
    print("Added detail source:", detail_source)
    
    source_ids = [listing_source["id"], detail_source["id"]]
    
    # 3. Trigger scrape
    scrape_payload = {"ids": source_ids}
    print(f"Triggering scrape for sources: {source_ids}...")
    r = httpx.post(f"{ORCHESTRATOR_URL}/api/v1/scraping/scrape-selected", json=scrape_payload, timeout=10.0)
    assert r.status_code == 200, f"Failed to trigger scrape: {r.text}"
    print("Scrape trigger response:", r.json())
    
    # 4. Poll and verify status transitions to completed
    print("Polling sources status...")
    max_wait = 60.0
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        r = httpx.get(f"{ORCHESTRATOR_URL}/api/v1/scraping/sources", timeout=10.0)
        assert r.status_code == 200, f"Failed to fetch sources: {r.text}"
        sources = r.json()
        
        status_map = {s["id"]: s["status"] for s in sources if s["id"] in source_ids}
        print(f"Current statuses: {status_map}")
        
        if all(status == "completed" for status in status_map.values()):
            print("SUCCESS: Both sources scraped and parsed successfully!")
            return True
            
        if any(status == "failed" for status in status_map.values()):
            print("ERROR: One or more sources failed to scrape/parse.")
            sys.exit(1)
            
        time.sleep(3.0)
        
    print("TIMEOUT: Scraping did not finish in 60 seconds.")
    sys.exit(1)

if __name__ == "__main__":
    test_scraping_flow()
