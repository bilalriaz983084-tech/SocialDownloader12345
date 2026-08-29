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
    """Facebook CDN URL ya Page URL se unique numeric Photo ID extract karta hai."""
    # Pattern 1: CDN filename pattern (e.g. /771909463_1625017112313549_...)
    match = re.search(r'/([0-9]+)_([0-9]{10,25})_[0-9]+_', url)
    if match:
        return match.group(2)

    # Pattern 2: fbid parameter
    fbid_match = re.search(r'fbid=([0-9]{10,25})', url)
    if fbid_match:
        return fbid_match.group(1)

    # Pattern 3: Fallback digit string
    digits = re.findall(r'[0-9]{13,20}', url)
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
    photos_map = {}
    seen_videos = set()

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

        def save_photo(clean_url: str, explicit_id: str = ""):
            if not is_valid_post_photo(clean_url):
                return
            pid = explicit_id or extract_photo_id(clean_url)
            if not pid:
                return

            # Agar image pehle se mojood na ho ya nayi wali HD/non-thumbnail ho to save karein
            if pid not in photos_map:
                photos_map[pid] = clean_url
            else:
                curr = photos_map[pid]
                if ("ctp=s" in curr or "p320x320" in curr) and ("cstp=mx" in clean_url or "stp=dst-jpg" in clean_url):
                    photos_map[pid] = clean_url

        # -------------------------------------------------------------
        # 1. Real-Time Network Responses Listener
        # -------------------------------------------------------------
        def handle_response(response):
            try:
                res_url = response.url
                content_type = response.headers.get("content-type", "").lower()

                if "fbcdn.net" in res_url and "oh=" in res_url:
                    clean = clean_fb_cdn_url(res_url)
                    save_photo(clean)

                if ("video/mp4" in content_type or ".mp4" in res_url) and "fbcdn.net" in res_url:
                    clean_v = clean_fb_cdn_url(res_url)
                    if clean_v and clean_v not in seen_videos and "bytestart" not in clean_v:
                        seen_videos.add(clean_v)
            except Exception:
                pass

        page.on("response", handle_response)

        try:
            # -------------------------------------------------------------
            # 2. Page Navigation & Popups Clearance
            # -------------------------------------------------------------
            desktop_url = re.sub(r'https?://(m|mbasic)\.facebook\.com', 'https://www.facebook.com', target_url)
            page.goto(desktop_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)

            for selector in ['div[aria-label="Close"]', 'div[aria-label="close"]', 'div[data-testid="cookie-policy-manage-dialog-accept-button"]']:
                try:
                    btn = page.locator(selector)
                    if btn.count() > 0 and btn.first.is_visible():
                        btn.first.click(force=True)
                except Exception:
                    pass

            # -------------------------------------------------------------
            # 3. Open Theater Mode & Step Through Full Album
            # -------------------------------------------------------------
            photo_link = page.locator('a[href*="/photo"], a[href*="photo.php"]').first
            
            if photo_link.count() > 0:
                try:
                    photo_link.click(force=True)
                    time.sleep(2)

                    seen_fbids = set()

                    # Album iterate loop
                    for _ in range(30):
                        # Active URL se Photo ID track karein
                        current_url = page.url
                        fbid_match = re.search(r'fbid=([0-9]+)', current_url) or re.search(r'/photo/([0-9]+)', current_url)
                        current_fbid = fbid_match.group(1) if fbid_match else ""

                        # Agar pehli photo dobara repeat ho aur kafi images collect ho chuki hon to loop break
                        if current_fbid and current_fbid in seen_fbids and len(seen_fbids) >= 11:
                            break

                        if current_fbid:
                            seen_fbids.add(current_fbid)

                        # Dialog/Theater ke active img tags inspect karein
                        active_imgs = page.locator('div[role="dialog"] img, div[data-visualcompletion="media-vc-image"] img').all()
                        for img in active_imgs:
                            try:
                                src = img.get_attribute("src")
                                if src:
                                    save_photo(clean_fb_cdn_url(src), explicit_id=current_fbid)
                            except Exception:
                                pass

                        # Next button click
                        next_btn = page.locator('div[aria-label="Next photo"], div[aria-label="Next"], [aria-label="See next image"]').first
                        if next_btn.count() > 0 and next_btn.is_visible():
                            next_btn.click(force=True)
                        else:
                            page.keyboard.press("ArrowRight")

                        # Image fetch & render buffer
                        time.sleep(1.2)

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
