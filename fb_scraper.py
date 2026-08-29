import os
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

def extract_photo_id(url: str) -> str:
    """Facebook CDN URL se unique photo ID nikalta hai taake duplicates filter ho sakein."""
    # Pattern: /<num>_<PHOTO_ID>_<num>_[na].jpg
    match = re.search(r'/([0-9]+)_([0-9]{10,25})_[0-9]+_', url)
    if match:
        return match.group(2)
    
    # Fallback pattern for other FB CDN structures
    digits = re.findall(r'[0-9]{12,20}', url)
    return digits[0] if digits else ""

def is_valid_post_photo(url: str) -> bool:
    if not url or "fbcdn.net" not in url:
        return False
    lower = url.lower()
    blocked = [
        "giphy", "emg1", "emoji", "rsrc.php", "cp0", 
        "p50x50", "p100x100", "p180x180", "safe_image.php", "profile"
    ]
    return not any(b in lower for b in blocked) and ("oh=" in url or "oe=" in url)

def extract_fb_media(target_url: str):
    # Dictionary use kar rahe hain: {photo_id: best_url}
    photos_map = {}
    seen_videos = set()
    first_seen_id = None

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled"
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            locale="en-US"
        )
        page = context.new_page()

        def save_photo_if_better(clean_url: str):
            nonlocal first_seen_id
            if not is_valid_post_photo(clean_url):
                return
            pid = extract_photo_id(clean_url)
            if not pid:
                return

            if first_seen_id is None:
                first_seen_id = pid

            # Agar photo pehli dafa aayi hai ya purani se behtar quality (non-crop/HD) hai to update karein
            if pid not in photos_map:
                photos_map[pid] = clean_url
            else:
                current_url = photos_map[pid]
                # Agar mojooda URL chhota thumbnail hai aur nayi HD hai
                if ("ctp=s" in current_url or "p320x320" in current_url) and ("cstp=mx" in clean_url or "stp=dst-jpg" in clean_url):
                    photos_map[pid] = clean_url

        # -------------------------------------------------------------
        # 1. Listen to Real-Time Network Responses
        # -------------------------------------------------------------
        def handle_response(response):
            try:
                res_url = response.url
                content_type = response.headers.get("content-type", "").lower()

                # CDN Photos listener
                if "fbcdn.net" in res_url and "oh=" in res_url:
                    clean = clean_fb_cdn_url(res_url)
                    save_photo_if_better(clean)

                # Video MP4 Stream Listener
                if ("video/mp4" in content_type or ".mp4" in res_url) and "fbcdn.net" in res_url:
                    clean_v = clean_fb_cdn_url(res_url)
                    if clean_v and clean_v not in seen_videos and "bytestart" not in clean_v:
                        seen_videos.add(clean_v)
            except Exception:
                pass

        page.on("response", handle_response)

        try:
            # -------------------------------------------------------------
            # 2. Open Page & Dismiss Blockers
            # -------------------------------------------------------------
            desktop_url = re.sub(r'https?://(m|mbasic)\.facebook\.com', 'https://www.facebook.com', target_url)
            page.goto(desktop_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)

            # Close Login Modals / Cookies Banner
            for selector in ['div[aria-label="Close"]', 'div[aria-label="close"]', 'div[data-testid="cookie-policy-manage-dialog-accept-button"]']:
                try:
                    btn = page.locator(selector)
                    if btn.count() > 0 and btn.first.is_visible():
                        btn.first.click(force=True)
                except Exception:
                    pass

            # -------------------------------------------------------------
            # 3. Open Theater Mode & Iterate Through Photos
            # -------------------------------------------------------------
            photo_link = page.locator('a[href*="/photo"], a[href*="photo.php"]').first
            
            if photo_link.count() > 0:
                try:
                    photo_link.click(force=True)
                    time.sleep(2)

                    consecutive_no_change = 0
                    last_count = 0

                    for _ in range(25):
                        # Current photo DOM image capture
                        current_img = page.locator('div[data-visualcompletion="media-vc-image"] img, div[role="dialog"] img').first
                        if current_img.count() > 0:
                            src = current_img.get_attribute("src")
                            if src:
                                save_photo_if_better(clean_fb_cdn_url(src))

                        # Next button click
                        next_btn = page.locator('div[aria-label="Next photo"], div[aria-label="Next"], div[aria-label="See next image"]').first
                        if next_btn.count() > 0 and next_btn.is_visible():
                            next_btn.click(force=True)
                        else:
                            page.keyboard.press("ArrowRight")
                        
                        time.sleep(0.8)

                        # Loop break condition: agar 3 dafa koi nayi unique photo na mile (end of album)
                        if len(photos_map) == last_count:
                            consecutive_no_change += 1
                            if consecutive_no_change >= 3:
                                break
                        else:
                            consecutive_no_change = 0
                            last_count = len(photos_map)

                except Exception as e:
                    print(f"Theater iteration error: {e}")

        except Exception as e:
            print(f"Scraper error: {e}")
        finally:
            browser.close()

    # Results Return
    if photos_map:
        return [{"url": url, "type": "jpg"} for url in photos_map.values()]

    if seen_videos:
        first_video = list(seen_videos)[0]
        return [{
            "url": first_video,
            "type": "mp4",
            "quality": "HD Video" if "hd" in first_video.lower() else "SD Video"
        }]

    return []

extract_all_fb_photos_sync = extract_fb_media
