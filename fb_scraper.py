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

def is_valid_post_photo(url: str) -> bool:
    if not url or "fbcdn.net" not in url:
        return False
    lower = url.lower()
    # Exclude small icons/emojis/placeholders
    blocked = ["giphy", "emg1", "emoji", "rsrc.php", "cp0", "p50x50", "p100x100", "p180x180", "safe_image.php"]
    return not any(b in lower for b in blocked) and ("oh=" in url or "oe=" in url)

def extract_fb_media(target_url: str):
    collected = []
    seen_urls = set()
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

        # -------------------------------------------------------------
        # 1. Listen to Real-Time Network & GraphQL Responses
        # -------------------------------------------------------------
        def handle_response(response):
            try:
                res_url = response.url
                content_type = response.headers.get("content-type", "").lower()

                # Direct Photo CDN URL match
                if "fbcdn.net" in res_url and is_valid_post_photo(res_url):
                    clean = clean_fb_cdn_url(res_url)
                    # Extract Unique Base Image Signature (digits before extension)
                    sig = re.findall(r'[0-9]{10,25}', clean)
                    key = sig[0] if sig else clean.split('?')[0]
                    if key not in seen_urls:
                        seen_urls.add(key)
                        collected.append({"url": clean, "type": "jpg"})

                # Intercept GraphQL / JSON payload for lazy-loaded carousel photos
                if "graphql" in res_url or "application/json" in content_type:
                    try:
                        text_data = response.text()
                        found_urls = re.findall(r'(https:[^"\'\s]+?fbcdn\.net[^"\'\s]+?(?:jpg|png|webp)[^"\'\s]*)', text_data)
                        for raw_u in found_urls:
                            clean = clean_fb_cdn_url(raw_u)
                            if is_valid_post_photo(clean):
                                sig = re.findall(r'[0-9]{10,25}', clean)
                                key = sig[0] if sig else clean.split('?')[0]
                                if key not in seen_urls:
                                    seen_urls.add(key)
                                    collected.append({"url": clean, "type": "jpg"})
                    except Exception:
                        pass

                # Video MP4 Stream Listener
                if ("video/mp4" in content_type or ".mp4" in res_url) and "fbcdn.net" in res_url:
                    clean_v = clean_fb_cdn_url(res_url)
                    if clean_v and clean_v not in seen_videos and "bytestart" not in clean_v:
                        seen_videos.add(clean_v)
                        collected.append({
                            "url": clean_v,
                            "type": "mp4",
                            "quality": "HD Video" if "hd" in clean_v.lower() else "SD Video"
                        })
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

            # Close Login Modals / Cookies Banner forcefully
            for selector in ['div[aria-label="Close"]', 'div[aria-label="close"]', 'div[data-testid="cookie-policy-manage-dialog-accept-button"]']:
                try:
                    btn = page.locator(selector)
                    if btn.count() > 0 and btn.first.is_visible():
                        btn.first.click(force=True)
                except Exception:
                    pass

            # -------------------------------------------------------------
            # 3. Open Theater Mode & Click Next Through All 11+ Photos
            # -------------------------------------------------------------
            photo_link = page.locator('a[href*="/photo"], a[href*="photo.php"]').first
            
            if photo_link.count() > 0:
                try:
                    photo_link.click(force=True)
                    time.sleep(2)

                    # Iterate up to 20 times to cover entire album/carousel
                    for _ in range(20):
                        # Try clicking explicit 'Next photo' button in theater mode
                        next_btn = page.locator('div[aria-label="Next photo"], div[aria-label="Next"], div[aria-label="See next image"]').first
                        if next_btn.count() > 0 and next_btn.is_visible():
                            next_btn.click(force=True)
                        else:
                            # Fallback: Keyboard right arrow
                            page.keyboard.press("ArrowRight")
                        
                        time.sleep(0.7)  # Network / DOM lazy load buffer
                except Exception as e:
                    print(f"Theater click iteration error: {e}")

            # -------------------------------------------------------------
            # 4. Fallback DOM Extraction for initial render
            # -------------------------------------------------------------
            for img in page.locator("img").all():
                try:
                    src = img.get_attribute("src")
                    if src and is_valid_post_photo(src):
                        clean = clean_fb_cdn_url(src)
                        sig = re.findall(r'[0-9]{10,25}', clean)
                        key = sig[0] if sig else clean.split('?')[0]
                        if key not in seen_urls:
                            seen_urls.add(key)
                            collected.append({"url": clean, "type": "jpg"})
                except Exception:
                    pass

        except Exception as e:
            print(f"Scraper error: {e}")
        finally:
            browser.close()

    photos = [item for item in collected if item["type"] == "jpg"]
    if photos:
        return photos

    videos = [item for item in collected if item["type"] == "mp4"]
    if videos:
        return [videos[0]]

    return collected

extract_all_fb_photos_sync = extract_fb_media
