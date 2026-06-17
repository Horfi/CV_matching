from playwright.sync_api import sync_playwright
import json

url = "https://www.tesla.com/careers/search/?site=NL"

for browser_type in ["firefox", "webkit"]:
    try:
        print(f"\nLaunching {browser_type} headless inside container...")
        with sync_playwright() as p:
            launcher = getattr(p, browser_type)
            browser = launcher.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1280, "height": 800}
            )
            page = context.new_page()
            
            print(f"Navigating to {url} using {browser_type}...")
            response = page.goto(url, wait_until="load", timeout=30000)
            print(f"[{browser_type}] Response status: {response.status if response else 'No Response'}")
            
            page.wait_for_timeout(3000)
            title = page.title()
            print(f"[{browser_type}] Page Title: {title}")
            
            if "Access Denied" in title or (response and response.status == 403):
                print(f"[{browser_type}] Access was Denied.")
            else:
                print(f"[{browser_type}] SUCCESS! Page Title is '{title}'. Evaluating fetch...")
                jobs_json = page.evaluate("""
                    async () => {
                        const response = await fetch('/cua-api/apps/careers/state');
                        if (!response.ok) {
                            throw new Error('CUA API status: ' + response.status);
                        }
                        return await response.json();
                    }
                """)
                listings = jobs_json.get("listings", [])
                print(f"[{browser_type}] SUCCESS! Retrieved {len(listings)} listings from Tesla.")
            browser.close()
    except Exception as e:
        print(f"[{browser_type}] Exception occurred:", e)
