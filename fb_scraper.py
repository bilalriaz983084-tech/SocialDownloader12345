import os
import re
import sys
import json
import urllib.parse
import requests

def clean_fb_cdn_url(raw_url: str) -> str:
    if not raw_url:
        return ""
    clean = str(raw_url).strip()
    clean = clean.replace(r'\/', '/').replace('\\"', '"')
    clean = clean.replace(r'\u0026', '&').replace('&amp;', '&')
    clean = urllib.parse.unquote(clean)
    return clean.strip("\"'<> ,\\")

def is_valid_post_photo(url: str) -> bool:
    if not url or "scontent" not in url or "fbcdn.net" not in url:
        return False
    lower = url.lower()
    blocked = [
        "p50x50", "p100x100", "p60x60", "s40x40", "cp0", "p32x32",
        "s50x50", "s100x100", "s150x150", "p180x180", "s200x200",
        "rsrc.php", "emoji.php", "safe_image.php", "static", "profile",
        "_a.jpg", "_a.png", "ads", "sponsor", "banner", "external"
    ]
    return not any(b in lower for b in blocked) and url.startswith("https://")

def extract_fb_media(target_url: str):
    collected = []
    seen_urls = set()
    seen_ids = set()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    desktop_url = target_url.replace("mbasic.facebook.com", "www.facebook.com").replace("m.facebook.com", "www.facebook.com")

    # 1. Fast HTTP extraction without browser
    try:
        session = requests.Session()
        res = session.get(desktop_url, headers=headers, timeout=12, allow_redirects=True)
        if res.status_code == 200:
            content = res.text

            # Videos
            video_patterns = [
                (r'\"playable_url_quality_hd\":\s*\"(https:[^\"]+?)\"', "HD"),
                (r'\"browser_native_hd_url\":\s*\"(https:[^\"]+?)\"', "HD"),
                (r'\"playable_url\":\s*\"(https:[^\"]+?)\"', "SD"),
                (r'\"browser_native_sd_url\":\s*\"(https:[^\"]+?)\"', "SD")
            ]
            for pattern, quality in video_patterns:
                for raw_vid in re.findall(pattern, content):
                    clean_vid = clean_fb_cdn_url(raw_vid)
                    if clean_vid and clean_vid not in seen_urls:
                        seen_urls.add(clean_vid)
                        collected.append({"url": clean_vid, "type": "mp4", "quality": quality})

            if collected:
                return collected

            # Images
            for uri in re.findall(r'\"uri\":\s*\"(https:[^\"]+?scontent[^\"]+?fbcdn\.net[^\"]+?)\"', content):
                clean_img = clean_fb_cdn_url(uri)
                if is_valid_post_photo(clean_img):
                    match = re.search(r'/([0-9]{8,25})_[0-9]+_[0-9]+', clean_img)
                    uid = match.group(1) if match else clean_img.split("?")[0]
                    if uid not in seen_ids:
                        seen_ids.add(uid)
                        collected.append({"url": clean_img, "type": "jpg"})

            if collected:
                return collected
    except Exception as e:
        print("[HTTP FB Error]:", repr(e))

    # 2. Playwright Fallback
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
            )
            context = browser.new_context(user_agent=headers["User-Agent"])
            page = context.new_page()

            page.goto(desktop_url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(2500)
            content = page.content()

            for uri in re.findall(r'\"uri\":\s*\"(https:[^\"]+?scontent[^\"]+?fbcdn\.net[^\"]+?)\"', content):
                clean_img = clean_fb_cdn_url(uri)
                if is_valid_post_photo(clean_img):
                    match = re.search(r'/([0-9]{8,25})_[0-9]+_[0-9]+', clean_img)
                    uid = match.group(1) if match else clean_img.split("?")[0]
                    if uid not in seen_ids:
                        seen_ids.add(uid)
                        collected.append({"url": clean_img, "type": "jpg"})

            context.close()
            browser.close()
    except Exception as e:
        print("[Playwright FB Scraper Error]:", repr(e))

    return collected

extract_all_fb_photos_sync = extract_fb_media
