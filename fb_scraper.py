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
    match = re.search(r'/([0-9]+)_([0-9]{10,25})_[0-9]+_', url)
    if match:
        return match.group(2)
    fbid = re.search(r'fbid=([0-9]{10,25})', url)
    if fbid:
        return fbid.group(1)
    digits = re.findall(r'[0-9]{13,22}', url)
    return digits[0] if digits else ""

def is_valid_post_photo(url: str) -> bool:
    if not url or "fbcdn.net" not in url:
        return False
    lower = url.lower()
    blocked = [
        "giphy", "emg1", "emoji", "rsrc.php", "cp0", 
        "p50x50", "p100x100", "p180x180", "s150x150", "s32x32", "s40x40", "s50x50", "safe_image.php", "profile", "cp1"
    ]
    if any(b in lower for b in blocked):
        return False
    # Sirf wahi link uthayein jo asli post ki high-res image ke hon
    return ("oh=" in url or "oe=" in url) and ("s720x720" in url or "s960x960" in url or "p720x720" in url or "p960x960" in url or "stp=" in url or "dst-jpg" in url or "tti" in lower or "oe=" in lower)

def extract_fb_media(target_url: str):
    photos_dict = {}

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
            viewport={"width": 1440, "height": 900},
            locale="en-US"
        )
        page = context.new_page()

        try:
            # Desktop version load karein kyunki usme high-res JSON payload mukammal hota hai
            desktop_url = re.sub(r'https?://(m|mbasic)\.facebook\.com', 'https://www.facebook.com', target_url)
            page.goto(desktop_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3.0)

            # Thoda scroll karein taake lazy-load items trigger ho jayein
            for _ in range(3):
                page.keyboard.press("PageDown")
                time.sleep(0.8)

            # Poore page ke HTML source se saare fbcdn image links uthayein
            html_content = page.content()
            raw_matches = re.findall(r'(https:[^"\'\s]+?fbcdn\.net[^"\'\s]+?(?:jpg|png|webp)[^"\'\s]*)', html_content)
            
            for raw_url in raw_matches:
                clean = clean_fb_cdn_url(raw_url)
                if is_valid_post_photo(clean):
                    pid = extract_photo_id(clean)
                    if pid:
                        if pid not in photos_dict:
                            photos_dict[pid] = clean
                        else:
                            # Agar pehle se choti image hai toh bari wali se replace kar dein
                            curr = photos_dict[pid]
                            if "s590x590" in curr or "p50x50" in curr:
                                photos_dict[pid] = clean
                    else:
                        # Fallback agar PID na mile
                        if clean not in photos_dict.values():
                            photos_dict[len(photos_dict)] = clean

        except Exception as e:
            print(f"Scraper error: {e}")
        finally:
            browser.close()

    return [{"url": url, "type": "jpg"} for url in photos_dict.values()]

extract_all_fb_photos_sync = extract_fb_media
