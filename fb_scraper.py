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
    blocked = ["giphy", "emg1", "emoji", "rsrc", "cp0", "p50x50", "p100x100", "p180x180", "safe_image", "profile"]
    return not any(b in lower for b in blocked) and ("oh=" in url or "oe=" in url)

def extract_fb_media(target_url: str):
    photos_dict = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage"
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="en-US"
        )
        page = context.new_page()

        try:
            # 1. Direct mbasic URL banayein taake login blocker na aaye
            mbasic_url = re.sub(r'https?://(www\.|m\.)?facebook\.com', 'https://mbasic.facebook.com', target_url)
            page.goto(mbasic_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(1.5)

            # 2. Check karein agar direct Album / "See All Photos" ka link mojood hai
            album_links = page.locator('a[href*="/media/set/"], a[href*="photos"], a[href*="album.php"]').all()
            if album_links:
                album_links[0].click()
                time.sleep(1.5)

            # 3. Post ke andar jitne photo detail pages ke links hain unko collect karein
            photo_page_links = []
            for link in page.locator('a[href*="photo.php"], a[href*="/photos/"]').all():
                href = link.get_attribute("href")
                if href and ("fbid=" in href or "/photos/" in href) and href not in photo_page_links:
                    if href.startswith("/"):
                        href = "https://mbasic.facebook.com" + href
                    photo_page_links.append(href)

            # Agar photo page links mil gaye (Album Mode)
            if photo_page_links:
                for link in photo_page_links:
                    try:
                        page.goto(link, wait_until="domcontentloaded", timeout=15000)
                        # Har photo page par Full Size / View Full Size ka link hota hai
                        full_size_link = page.locator('a[href*="fbcdn.net"], a:has-text("View full size"), a:has-text("View Full Size")').first
                        
                        img_url = ""
                        if full_size_link.count() > 0:
                            img_url = full_size_link.get_attribute("href")
                        
                        if not img_url:
                            img = page.locator('img[src*="fbcdn.net"]').first
                            if img.count() > 0:
                                img_url = img.get_attribute("src")

                        if img_url and is_valid_post_photo(img_url):
                            clean = clean_fb_cdn_url(img_url)
                            pid = extract_photo_id(clean) or extract_photo_id(link)
                            if pid:
                                photos_dict[pid] = clean
                    except Exception:
                        pass
            else:
                # 4. Fallback: Standard Post View se saari images uthana
                for img in page.locator('img[src*="fbcdn.net"]').all():
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
