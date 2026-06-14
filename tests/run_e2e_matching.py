import sys
import time
import httpx

BFF_URL = "http://localhost:8000"

def test_matching_flow():
    print("Testing CV Matching Flow via BFF Gateway...")
    
    cv_data = {
        "name": "Jane Doe",
        "contact_info": "jane.doe@example.com, +1-555-0199",
        "skills": ["Python", "FastAPI", "React", "Docker", "DevOps"],
        "experience": "Senior Backend Software Engineer with 5+ years of experience building scalable APIs, Docker containers, and managing PostgreSQL database layers."
    }
    
    # 1. Trigger matching
    print("Triggering matching workflow...")
    r = httpx.post(f"{BFF_URL}/api/v1/trigger", json={"cv_data": cv_data}, timeout=10.0)
    assert r.status_code == 200, f"Trigger failed: {r.text}"
    
    trigger_res = r.json()
    assert trigger_res.get("status") == "started", f"Unexpected status: {trigger_res}"
    thread_id = trigger_res.get("thread_id")
    print(f"Workflow started with thread_id: {thread_id}")
    
    # 2. Poll status
    print("Polling matching workflow status...")
    max_wait = 30.0
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        r = httpx.get(f"{BFF_URL}/api/v1/status/{thread_id}", timeout=10.0)
        assert r.status_code == 200, f"Failed to fetch status: {r.text}"
        
        status_data = r.json()
        status = status_data.get("status")
        print(f"Current status: {status}")
        
        if status == "review_pending" or status == "matching_complete":
            matched_jobs = status_data.get("matched_jobs", [])
            print(f"SUCCESS: Matching completed! Found {len(matched_jobs)} matched jobs:")
            for job in matched_jobs:
                print(f"- {job['title']} at {job['company']} (Score: {job['score']*100}%)")
            return True
            
        if "failed" in status:
            print(f"ERROR: Workflow failed with status: {status}")
            sys.exit(1)
            
        time.sleep(2.0)
        
    print("TIMEOUT: Matching workflow did not complete in 30 seconds.")
    sys.exit(1)

if __name__ == "__main__":
    test_matching_flow()
