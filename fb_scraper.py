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
    return "oh=" in url or "oe=" in url

def extract_fb_media(target_url: str):
    photos_dict = {}

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
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1",
            viewport={"width": 390, "height": 844},
            locale="en-US"
        )
        page = context.new_page()

        try:
            mobile_url = re.sub(r'https?://(www\.)?facebook\.com', 'https://m.facebook.com', target_url)
            page.goto(mobile_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3.0)

            # Sirf post ke andar mojood main images ko target karein (comments/icons ignore honge)
            img_elements = page.locator('div[data-sigil="m-story-view"] img, article img, div[role="article"] img').all()
            for img in img_elements:
                try:
                    src = img.get_attribute("src")
                    if src and is_valid_post_photo(src):
                        clean = clean_fb_cdn_url(src)
                        pid = extract_photo_id(clean)
                        if pid:
                            # Agar choti resolution wali hai toh skip karein ya bari se replace karein
                            if pid not in photos_dict:
                                photos_dict[pid] = clean
                        else:
                            # Agar PID nahi milti lekin valid URL hai
                            if clean not in photos_dict.values():
                                photos_dict[len(photos_dict)] = clean
                except Exception:
                    pass

        except Exception as e:
            print(f"Scraper error: {e}")
        finally:
            browser.close()

    return [{"url": url, "type": "jpg"} for url in photos_dict.values()]

extract_all_fb_photos_sync = extract_fb_media
