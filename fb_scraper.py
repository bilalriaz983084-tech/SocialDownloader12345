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
    # Match standard FB photo identifiers
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
        "p50x50", "p100x100", "p180x180", "safe_image.php", "profile"
    ]
    return not any(b in lower for b in blocked) and ("oh=" in url or "oe=" in url)

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
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            locale="en-US"
        )
        page = context.new_page()

        try:
            # 1. Desktop URL load
            desktop_url = re.sub(r'https?://(m|mbasic)\.facebook\.com', 'https://www.facebook.com', target_url)
            page.goto(desktop_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(2.5)

            # Close Cookie / Login Modals
            for sel in ['div[aria-label="Close"]', 'div[aria-label="close"]', 'div[data-testid="cookie-policy-manage-dialog-accept-button"]']:
                try:
                    btn = page.locator(sel).first
                    if btn.count() > 0 and btn.is_visible():
                        btn.click(force=True)
                except Exception:
                    pass

            # 2. Extract directly from Page Embedded JSON Scripts (Contains all 11 photos payload)
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
                            curr = photos_dict[pid]
                            if ("ctp=s" in curr or "s590x590" in curr) and ("mx1170" in clean or "stp=dst-jpg" in clean):
                                photos_dict[pid] = clean

            # 3. Agar images 11 se kam hon to Theater Mode se slide karein
            if len(photos_dict) < 11:
                first_photo = page.locator('a[href*="/photo"], a[href*="photo.php"]').first
                if first_photo.count() > 0:
                    try:
                        first_photo.click(force=True)
                        time.sleep(1.5)

                        for _ in range(15):
                            img_elem = page.locator('div[role="dialog"] img[src*="fbcdn.net"], div[data-visualcompletion="media-vc-image"] img').first
                            if img_elem.count() > 0:
                                src = img_elem.get_attribute("src")
                                if src and is_valid_post_photo(src):
                                    clean = clean_fb_cdn_url(src)
                                    pid = extract_photo_id(clean)
                                    if pid:
                                        photos_dict[pid] = clean

                            # Click next photo
                            next_btn = page.locator('div[aria-label="Next photo"], div[aria-label="Next"], [aria-label="See next image"]').first
                            if next_btn.count() > 0 and next_btn.is_visible():
                                next_btn.click(force=True)
                            else:
                                page.keyboard.press("ArrowRight")
                            
                            time.sleep(0.8)

                            if len(photos_dict) >= 11:
                                break
                    except Exception:
                        pass

        except Exception as e:
            print(f"Scraper error: {e}")
        finally:
            browser.close()

    return [{"url": url, "type": "jpg"} for url in photos_dict.values()]

extract_all_fb_photos_sync = extract_fb_media
