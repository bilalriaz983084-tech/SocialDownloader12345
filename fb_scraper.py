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
    blocked = ["giphy", "emg1", "emoji", "rsrc", "cp0", "p50x50", "p100x100", "p180x180", "safe_image.php"]
    return not any(b in lower for b in blocked) and ("oh=" in url or "oe=" in url)

def extract_fb_media(target_url: str):
    collected = []
    seen_ids = set()
    seen_videos = set()

    with sync_playwright() as p:
        # Browser launch
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
            viewport={"width": 1280, "height": 900},
            locale="en-US"
        )
        page = context.new_page()

        # -------------------------------------------------------------
        # 1. Listen to Real-Time Network Responses (Photos & Videos)
        # -------------------------------------------------------------
        def handle_response(response):
            try:
                res_url = response.url
                # Photos Listener
                if "fbcdn.net/v/t39." in res_url and "oh=" in res_url:
                    clean = clean_fb_cdn_url(res_url)
                    if is_valid_post_photo(clean):
                        photo_id_match = re.search(r'\/([0-9_]+)_[na]\.', clean) or re.search(r'\/([0-9]{8,25})_', clean)
                        if photo_id_match:
                            pid = photo_id_match.group(1)
                            if pid not in seen_ids:
                                seen_ids.add(pid)
                                collected.append({"url": clean, "type": "jpg"})

                # Video MP4 Stream Listener
                content_type = response.headers.get("content-type", "").lower()
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
            # 2. Navigate to Facebook Post
            # -------------------------------------------------------------
            desktop_url = re.sub(r'https?://(m|mbasic)\.facebook\.com', 'https://www.facebook.com', target_url)
            page.goto(desktop_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(2.5)

            # Close Login Popups
            try:
                close_btn = page.query_selector('div[aria-label="Close"], [aria-label="close"], div[role="button"][tabindex="0"]')
                if close_btn:
                    close_btn.click()
            except Exception:
                pass

            # Scroll down to load grid
            page.mouse.wheel(0, 1000)
            time.sleep(1.5)

            # -------------------------------------------------------------
            # 3. Theater Mode Navigation (For Album Photos)
            # -------------------------------------------------------------
            clickable_photos = page.query_selector_all('a[href*="/photo"], a[href*="photo.php"]')
            if clickable_photos:
                try:
                    clickable_photos[0].click()
                    time.sleep(1.5)
                    for _ in range(15):  # Iterates up to 15 album photos
                        page.keyboard.press("ArrowRight")
                        time.sleep(0.5)
                except Exception:
                    pass

            # -------------------------------------------------------------
            # 4. Fallback: Parse HTML for Video Patterns if no photo clicked
            # -------------------------------------------------------------
            photos = [item for item in collected if item["type"] == "jpg"]
            if not photos:
                content = page.content()
                video_patterns = [
                    (r'\"playable_url_quality_hd\":\s*\"(https:[^\"]+?)\"', "HD Video"),
                    (r'\"browser_native_hd_url\":\s*\"(https:[^\"]+?)\"', "HD Video"),
                    (r'\"playable_url\":\s*\"(https:[^\"]+?)\"', "SD Video"),
                    (r'\"browser_native_sd_url\":\s*\"(https:[^\"]+?)\"', "SD Video")
                ]
                for pattern, quality in video_patterns:
                    matches = re.findall(pattern, content)
                    for raw_vid in matches:
                        clean_vid = clean_fb_cdn_url(raw_vid)
                        if clean_vid and clean_vid not in seen_videos:
                            seen_videos.add(clean_vid)
                            collected.append({"url": clean_vid, "type": "mp4", "quality": quality})

        except Exception as e:
            print(f"Scraper error: {e}")
        finally:
            browser.close()

    # Rule: Agar photos milti hain to sirf photos return hongi, warna videos
    photos = [item for item in collected if item["type"] == "jpg"]
    if photos:
        return photos

    videos = [item for item in collected if item["type"] == "mp4"]
    if videos:
        return [videos[0]]

    return collected

extract_all_fb_photos_sync = extract_fb_media
