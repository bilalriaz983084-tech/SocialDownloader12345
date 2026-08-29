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
    # 1. Standard FB CDN format (e.g. /771909463_1625017112313549_...)
    match = re.search(r'/([0-9]+)_([0-9]{10,25})_[0-9]+_', url)
    if match:
        return match.group(2)
    
    # 2. Query param fbid
    fbid_match = re.search(r'fbid=([0-9]{10,25})', url)
    if fbid_match:
        return fbid_match.group(1)

    # 3. Fallback digit sequence
    digits = re.findall(r'[0-9]{13,22}', url)
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
        
        # Mobile viewport use karein taake login popup na aye aur photos easily scroll hon
        context = browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1",
            viewport={"width": 430, "height": 932},
            is_mobile=True,
            has_touch=True,
            locale="en-US"
        )
        page = context.new_page()

        def save_photo(clean_url: str):
            if not is_valid_post_photo(clean_url):
                return
            pid = extract_photo_id(clean_url)
            if not pid:
                return

            if pid not in photos_map:
                photos_map[pid] = clean_url
            else:
                curr = photos_map[pid]
                # High resolution version ko retain karein
                if ("ctp=s" in curr or "s590x590" in curr or "p320x320" in curr) and ("mx1170" in clean_url or "cstp=mx" in clean_url or "dst-jpg" in clean_url):
                    photos_map[pid] = clean_url

        def handle_response(response):
            try:
                res_url = response.url
                content_type = response.headers.get("content-type", "").lower()

                # Direct CDN response
                if "fbcdn.net" in res_url and "oh=" in res_url:
                    save_photo(clean_fb_cdn_url(res_url))

                # GraphQL payload mein chupi hui photos extract karna
                if "graphql" in res_url or "application/json" in content_type:
                    try:
                        text_data = response.text()
                        found = re.findall(r'(https:[^"\'\s]+?fbcdn\.net[^"\'\s]+?(?:jpg|png|webp)[^"\'\s]*)', text_data)
                        for u in found:
                            save_photo(clean_fb_cdn_url(u))
                    except Exception:
                        pass

                # Video Listener
                if ("video/mp4" in content_type or ".mp4" in res_url) and "fbcdn.net" in res_url:
                    clean_v = clean_fb_cdn_url(res_url)
                    if clean_v and clean_v not in seen_videos and "bytestart" not in clean_v:
                        seen_videos.add(clean_v)
            except Exception:
                pass

        page.on("response", handle_response)

        try:
            # Facebook standard URL load karein
            clean_url = target_url.replace("mbasic.", "").replace("m.", "")
            page.goto(clean_url, wait_until="networkidle", timeout=35000)
            time.sleep(2)

            # Close popup if any
            for sel in ['div[aria-label="Close"]', 'div[role="button"]:has-text("Close")', '[aria-label="Decline optional cookies"]']:
                try:
                    btn = page.locator(sel)
                    if btn.count() > 0 and btn.first.is_visible():
                        btn.first.click(force=True)
                except Exception:
                    pass

            # 1. Pehle DOM ke images save karein
            for img in page.locator("img").all():
                try:
                    src = img.get_attribute("src")
                    if src:
                        save_photo(clean_fb_cdn_url(src))
                except Exception:
                    pass

            # 2. Album / See More Photos pe click karein
            more_btn = page.locator('a[href*="/photos/"], a[href*="album"], text=/\\+[0-9]+/').first
            if more_btn.count() > 0 and more_btn.is_visible():
                try:
                    more_btn.click(force=True)
                    time.sleep(2.5)
                except Exception:
                    pass

            # 3. Step-by-Step Horizontal & Vertical Scroll taake lazy loader trigger ho
            for _ in range(12):
                page.mouse.wheel(0, 800)
                # Touch swipe simulation for carousel
                page.touchscreen.tap(200, 400)
                time.sleep(0.8)

            # 4. Agar photo open hoti hai to swipe right karein
            first_photo = page.locator('a[href*="/photo"], a[href*="photo.php"]').first
            if first_photo.count() > 0:
                try:
                    first_photo.click(force=True)
                    time.sleep(1.5)
                    for _ in range(15):
                        # Swipe / Arrow for mobile photo viewer
                        page.keyboard.press("ArrowRight")
                        time.sleep(0.8)
                except Exception:
                    pass

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
