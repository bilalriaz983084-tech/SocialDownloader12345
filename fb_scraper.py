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
    """Extracts actual numeric Photo ID to strictly eliminate duplicates."""
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
    # Profile pics, emojis, icons, ads, thumbnails ko strictly block karein
    blocked = [
        "giphy", "emg1", "emoji", "rsrc", "cp0", "p50x50", 
        "p100x100", "p180x180", "p320x320", "safe_image", "profile"
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
        # Desktop context for full resolution rendering
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            locale="en-US"
        )
        page = context.new_page()

        try:
            # 1. Desktop URL load karein
            clean_target = re.sub(r'https?://(m|mbasic)\.facebook\.com', 'https://www.facebook.com', target_url)
            page.goto(clean_target, wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)

            # Close Login Dialog if present
            try:
                close_btn = page.locator('div[aria-label="Close"], div[aria-label="close"], div[data-testid="cookie-policy-manage-dialog-accept-button"]').first
                if close_btn.count() > 0 and close_btn.is_visible():
                    close_btn.click(force=True)
            except Exception:
                pass

            # 2. Open First Photo in Theater Mode
            first_photo = page.locator('a[href*="/photo"], a[href*="photo.php"]').first
            if first_photo.count() > 0:
                first_photo.click(force=True)
                time.sleep(2)

                seen_dialog_ids = set()

                # Sirf Theater Dialog ke andar se active photo extract karein
                for _ in range(15):  # 11 photos ke liye max 15 steps
                    # Current Active Photo Selector (Sirf Main Center Image)
                    img_elem = page.locator('div[data-visualcompletion="media-vc-image"] img, div[role="dialog"] img[data-visualcompletion="media-vc-image"]').first
                    
                    if img_elem.count() == 0:
                        # Fallback for standard dialog image
                        img_elem = page.locator('div[role="dialog"] img[src*="fbcdn.net"]').first

                    if img_elem.count() > 0:
                        src = img_elem.get_attribute("src")
                        if src and is_valid_post_photo(src):
                            clean = clean_fb_cdn_url(src)
                            pid = extract_photo_id(clean)
                            if pid:
                                # Agar loop dobara pehli photo par rotate ho gaya to foran stop karein
                                if pid in seen_dialog_ids and len(seen_dialog_ids) >= 10:
                                    break
                                seen_dialog_ids.add(pid)
                                photos_dict[pid] = clean

                    # Next button click karein
                    next_btn = page.locator('div[aria-label="Next photo"], div[aria-label="Next"], [aria-label="See next image"]').first
                    if next_btn.count() > 0 and next_btn.is_visible():
                        next_btn.click(force=True)
                    else:
                        page.keyboard.press("ArrowRight")

                    time.sleep(1.2)  # Photo load hone ka wait

            # Fallback agar click na ho sakay: Sirf post container ke andar wali images lein
            if not photos_dict:
                post_imgs = page.locator('div[role="article"] img, div[data-ad-preview="message"] ~ div img').all()
                for img in post_imgs:
                    src = img.get_attribute("src")
                    if src and is_valid_post_photo(src):
                        clean = clean_fb_cdn_url(src)
                        pid = extract_photo_id(clean)
                        if pid:
                            photos_dict[pid] = clean

        except Exception as e:
            print(f"Scraper error: {e}")
        finally:
            browser.close()

    return [{"url": url, "type": "jpg"} for url in photos_dict.values()]

extract_all_fb_photos_sync = extract_fb_media
