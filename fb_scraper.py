import os
import re
import html as html_lib
import urllib.parse
import time
import requests
from playwright.sync_api import sync_playwright

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
}

def clean_fb_cdn_url(raw_url: str) -> str:
    if not raw_url:
        return ""
    clean = str(raw_url).strip()
    try:
        clean = clean.encode('utf-8').decode('unicode-escape')
    except Exception:
        pass
    clean = clean.replace(r'\/', '/')
    clean = html_lib.unescape(clean)
    clean = clean.replace(r'\u0026', '&').replace('&amp;', '&')
    return clean.strip("\"'<> ,\\")

def is_valid_post_photo(url: str) -> bool:
    if not url or "fbcdn.net" not in url:
        return False
    lower = url.lower()
    blocked = [
        "p50x50", "p100x100", "p60x60", "s40x40", "cp0", "p32x32",
        "s50x50", "s100x100", "s150x150", "p180x180", "s200x200",
        "rsrc.php", "emoji.php", "safe_image.php", "static", "profile",
        "_a.jpg", "_a.png", "ads", "sponsor", "banner", "external",
        "t39.1997-6", "t39.1998-6", "100x100", "giphy", "emg1"
    ]
    return not any(b in lower for b in blocked) and url.startswith("https://") and ("oh=" in url and "oe=" in url)

def extract_from_raw_html(html_text: str, seen_ids: set, collected: list):
    # Match JSON script tags
    script_matches = re.findall(r'\"(?:image|photo_image|full_image|viewer_image)\":\s*\{\"uri\":\s*\"(https:[^\"]+?fbcdn\.net[^\"]+?)\"', html_text)
    script_matches += re.findall(r'\"(?:uri|src|preview_image)\":\s*\"(https:[^\"]+?fbcdn\.net[^\"]+?)\"', html_text)
    
    # Direct CDN regex
    cdn_matches = re.findall(r'https:\/\/[a-zA-Z0-9.\-_]*?\.fbcdn\.net\/v\/t39\.[0-9\-]+-6\/[^"\'\s<>\\]+', html_text)

    all_links = script_matches + cdn_matches

    for link in all_links:
        clean = clean_fb_cdn_url(link)
        if is_valid_post_photo(clean):
            match = re.search(r'/([0-9]{8,25})_', clean)
            uid = match.group(1) if match else clean.split("?")[0].split("/")[-1]
            if uid not in seen_ids:
                seen_ids.add(uid)
                collected.append({"url": clean, "type": "jpg"})

def extract_fb_media(target_url: str):
    collected = []
    seen_ids = set()

    # Step 0: Resolve canonical URL
    resolved_url = target_url
    try:
        session = requests.Session()
        res_check = session.get(target_url, headers=HEADERS, allow_redirects=True, timeout=10)
        resolved_url = res_check.url or target_url
        extract_from_raw_html(res_check.text, seen_ids, collected)
    except Exception as e:
        print("Direct resolve warning:", e)

    # Agar direct request se hi 2+ images mil gayi to return kar dein (Fastest)
    if len(collected) >= 2:
        return collected

    # Step 1: Headless Automation via Browserless
    api_key = os.environ.get("BROWSERLESS_API_KEY", "2V9PPrLczaJ3bPxdca15920493ce5f1ff8d4201d5fe50a8af")
    ws_endpoint = f"wss://production-sfo.browserless.io?token={api_key}&stealth=true"

    try:
        with sync_playwright() as p:
            browser = None
            try:
                browser = p.chromium.connect_over_cdp(ws_endpoint, timeout=15000)
            except Exception:
                try:
                    browser = p.chromium.launch(headless=True)
                except Exception:
                    pass

            if browser:
                context = browser.new_context(
                    user_agent=HEADERS["User-Agent"],
                    viewport={"width": 1280, "height": 900}
                )
                page = context.new_page()

                def handle_response(response):
                    try:
                        res_url = response.url
                        if "fbcdn.net/v/t39." in res_url:
                            clean_img = clean_fb_cdn_url(res_url)
                            if is_valid_post_photo(clean_img):
                                match = re.search(r'/([0-9]{8,25})_', clean_img)
                                uid = match.group(1) if match else clean_img.split("?")[0].split("/")[-1]
                                if uid not in seen_ids:
                                    seen_ids.add(uid)
                                    collected.append({"url": clean_img, "type": "jpg"})
                    except Exception:
                        pass

                page.on("response", handle_response)

                try:
                    page.goto(resolved_url, wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_timeout(2000)

                    # Close login / cookie banners
                    try:
                        close_btn = page.query_selector('div[aria-label="Close"], [aria-label="Decline optional cookies"]')
                        if close_btn:
                            close_btn.click()
                    except Exception:
                        pass

                    page.mouse.wheel(0, 1000)
                    page.wait_for_timeout(1000)

                    # Trigger photo viewer
                    clickable_photos = page.query_selector_all('a[href*="/photo"], a[href*="photo.php"]')
                    if clickable_photos:
                        try:
                            clickable_photos[0].click()
                            page.wait_for_timeout(1000)
                            for _ in range(8):
                                page.keyboard.press("ArrowRight")
                                page.wait_for_timeout(400)
                        except Exception:
                            pass

                    # Extract rendered DOM
                    content = page.content()
                    extract_from_raw_html(content, seen_ids, collected)

                    # Check for video post if no photos
                    if not collected:
                        video_patterns = [
                            (r'\"playable_url_quality_hd\":\s*\"(https:[^\"]+?)\"', "HD"),
                            (r'\"browser_native_hd_url\":\s*\"(https:[^\"]+?)\"', "HD"),
                            (r'\"playable_url\":\s*\"(https:[^\"]+?)\"', "SD"),
                            (r'\"browser_native_sd_url\":\s*\"(https:[^\"]+?)\"', "SD")
                        ]
                        for pattern, quality in video_patterns:
                            matches = re.findall(pattern, content)
                            for raw_vid in matches:
                                clean_vid = clean_fb_cdn_url(raw_vid)
                                if clean_vid and "fbcdn.net" in clean_vid:
                                    return [{
                                        "url": clean_vid,
                                        "type": "mp4",
                                        "quality": f"Facebook Video ({quality})"
                                    }]

                except Exception as inner_e:
                    print("Browser inner error:", inner_e)
                finally:
                    browser.close()

    except Exception as e:
        print("Playwright connection exception:", e)

    # Fallback to OpenGraph meta tag if single photo post
    if not collected and 'res_check' in locals():
        og_match = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', res_check.text)
        if og_match:
            og_url = clean_fb_cdn_url(og_match.group(1))
            if is_valid_post_photo(og_url):
                collected.append({"url": og_url, "type": "jpg"})

    return collected

extract_all_fb_photos_sync = extract_fb_media
