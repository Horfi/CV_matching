import time
import httpx
import sys

def main():
    url = "http://localhost:8001/api/v1/upload-cv"
    print(f"Uploading example_cv.png to {url}...")
    
    try:
        with open("example_cv.png", "rb") as f:
            files = {"file": ("example_cv.png", f.read(), "image/png")}
            response = httpx.post(url, files=files, timeout=30.0)
    except Exception as e:
        print(f"Failed to upload: {e}")
        sys.exit(1)
        
    if response.status_code != 200:
        print(f"Upload failed: {response.status_code} - {response.text}")
        sys.exit(1)
        
    result = response.json()
    print("Upload response:", result)
    
    thread_id = result.get("thread_id")
    if not thread_id:
        print("No thread_id returned!")
        sys.exit(1)
        
    status_url = f"http://localhost:8001/api/v1/status/{thread_id}"
    print(f"Polling status of thread {thread_id}...")
    
    for i in range(15):
        time.sleep(2)
        try:
            status_resp = httpx.get(status_url, timeout=10.0)
            if status_resp.status_code == 200:
                state = status_resp.json()
                print(f"Poll {i+1}: status = {state.get('status')}")
                if "failed" in state.get("status", ""):
                    print("Workflow failed! State details:")
                    print(state)
                    sys.exit(1)
                if state.get("status") in ["review_pending", "submitted", "completed"]:
                    print("Workflow successfully completed processing or is waiting for review!")
                    print("State details:")
                    import pprint
                    pprint.pprint(state)
                    break
            else:
                print(f"Poll {i+1} failed: {status_resp.status_code} - {status_resp.text}")
        except Exception as e:
            print(f"Poll {i+1} error: {e}")
            
if __name__ == "__main__":
    main()
