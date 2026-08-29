import re
import html as html_lib
import time
from playwright.sync_api import sync_playwright

def clean_fb_cdn_url(raw_url: str) -> str:
    if not raw_url:
        return ""
    clean = str(raw_url).replace(r'\/', '/').replace(r'\u0026', '&')
    clean = html_lib.unescape(clean)
    clean = clean.replace('&amp;', '&')
    return clean.strip("\"'<> ,\\")

def extract_fb_media(target_url: str):
    image_urls = []
    seen_ids = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--single-process",
                "--disable-blink-features=AutomationControlled"
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
            locale="en-US"
        )
        page = context.new_page()

        # Network responses intercept karne ka function
        def handle_response(response):
            try:
                res_url = response.url
                if "fbcdn.net/v/t39." in res_url and "oh=" in res_url:
                    clean = clean_fb_cdn_url(res_url)
                    if not any(ign in clean for ign in ["giphy", "emg1", "emoji", "rsrc", "cp0"]):
                        photo_id_match = re.search(r'\/([0-9_]+)_[na]\.', clean)
                        if photo_id_match:
                            pid = photo_id_match.group(1)
                            if pid not in seen_ids:
                                seen_ids.add(pid)
                                image_urls.append(clean)
            except Exception:
                pass

        page.on("response", handle_response)

        try:
            # Desktop URL load karein
            desktop_url = re.sub(r'https?://(m|mbasic)\.facebook\.com', 'https://www.facebook.com', target_url)
            page.goto(desktop_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)

            # Login/Cookie modal close karein agar aaye
            try:
                close_btn = page.query_selector('div[aria-label="Close"]')
                if close_btn:
                    close_btn.click()
            except Exception:
                pass

            # Scroll down to load grid
            page.mouse.wheel(0, 1000)
            time.sleep(2)

            # Pehli image par click karke Theater mode kholen
            clickable_photos = page.query_selector_all('a[href*="/photo"], a[href*="photo.php"]')
            if clickable_photos:
                try:
                    clickable_photos[0].click()
                    time.sleep(2)
                    
                    # Right arrow key se ek ek karke saari images load karwayen
                    for _ in range(15): 
                        page.keyboard.press("ArrowRight")
                        time.sleep(0.8)
                except Exception:
                    pass

            # Fallback: HTML source se bhi check kar len
            content = page.content()
            cdn_matches = re.findall(r'https:\/\/[a-zA-Z0-9.\-_]*?\.fbcdn\.net\/v\/t39\.[0-9\-]+-6\/[^"\'\s<>\\]+', content)
            for link in cdn_matches:
                clean = clean_fb_cdn_url(link)
                if any(ign in clean for ign in ["giphy.com", "emg1", "rsrc.php", "emoji.php", "cp0"]):
                    continue
                if "oh=" not in clean or "oe=" not in clean:
                    continue
                photo_id_match = re.search(r'\/([0-9_]+)_[na]\.', clean)
                if photo_id_match:
                    pid = photo_id_match.group(1)
                    if pid not in seen_ids:
                        seen_ids.add(pid)
                        image_urls.append(clean)

        except Exception as e:
            print(f"Extraction exception: {e}")
        finally:
            browser.close()

    return [{"url": url, "type": "jpg"} for url in image_urls]

extract_all_fb_photos_sync = extract_fb_media
