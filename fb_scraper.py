import os
import re
import html as html_lib
import time
import requests
from playwright.sync_api import sync_playwright

def clean_fb_cdn_url(raw_url: str) -> str:
    if not raw_url:
        return ""
    clean = str(raw_url).replace(r'\/', '/').replace(r'\u0026', '&')
    clean = html_lib.unescape(clean)
    clean = clean.replace('&amp;', '&')
    return clean.strip("\"'<> ,\\")

def extract_photo_id(url: str) -> str:
    # 1. Standard CDN filename format: /<num>_<PHOTO_ID>_<num>_
    match = re.search(r'/([0-9]+)_([0-9]{10,25})_[0-9]+_', url)
    if match:
        return match.group(2)
    # 2. fbid parameter
    fbid = re.search(r'fbid=([0-9]{10,25})', url)
    if fbid:
        return fbid.group(1)
    # 3. Digits fallback
    digits = re.findall(r'[0-9]{13,22}', url)
    return digits[0] if digits else ""

def is_valid_post_photo(url: str) -> bool:
    if not url or "fbcdn.net" not in url:
        return False
    lower = url.lower()
    blocked = [
        "giphy", "emg1", "emoji", "rsrc.php", "cp0", 
        "p50x50", "p100x100", "p180x180", "s150x150", "s32x32", "s40x40", "s50x50", 
        "safe_image.php", "profile", "cp1", "static.xx"
    ]
    return not any(b in lower for b in blocked) and ("oh=" in url or "oe=" in url)

def resolve_fb_share_url(share_url: str) -> str:
    """Share link (/share/p/...) ko expand kar ke asal post URL banata hai."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        }
        res = requests.get(share_url, headers=headers, allow_redirects=True, timeout=10)
        return res.url
    except Exception:
        return share_url

def extract_fb_media(target_url: str):
    photos_dict = {}

    # Step 1: Share URL redirect resolve karein
    resolved_url = resolve_fb_share_url(target_url)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
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
            # Step 2: Resolved desktop URL load karein
            final_desktop_url = resolved_url.replace("m.facebook.com", "www.facebook.com").replace("mbasic.facebook.com", "www.facebook.com")
            page.goto(final_desktop_url, wait_until="domcontentloaded", timeout=35000)
            time.sleep(3)

            # Close Login/Cookie popup if appears
            for sel in ['div[aria-label="Close"]', 'div[aria-label="close"]', 'div[data-testid="cookie-policy-manage-dialog-accept-button"]']:
                try:
                    btn = page.locator(sel).first
                    if btn.count() > 0 and btn.is_visible():
                        btn.click(force=True)
                except Exception:
                    pass

            # Step 3: Raw page HTML se script payload extract karein (Contains all 11 photos)
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
                            # High resolution version prioritize karein
                            if ("ctp=s" in curr or "s590x590" in curr or "p320x320" in curr) and ("mx1170" in clean or "dst-jpg" in clean):
                                photos_dict[pid] = clean

            # Step 4: Fallback DOM inspection
            if not photos_dict:
                for img in page.locator('img[src*="fbcdn.net"]').all():
                    try:
                        src = img.get_attribute("src")
                        if src and is_valid_post_photo(src):
                            clean = clean_fb_cdn_url(src)
                            pid = extract_photo_id(clean)
                            if pid:
                                photos_dict[pid] = clean
                    except Exception:
                        pass

        except Exception as e:
            print(f"Scraper error: {e}")
        finally:
            browser.close()

    return [{"url": url, "type": "jpg"} for url in photos_dict.values()]

extract_all_fb_photos_sync = extract_fb_media
