import os
import re
import html as html_lib
import urllib.parse
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

def parse_html_for_photos(html_text: str, seen_ids: set, collected: list):
    # 1. Match full high-res FB image JSON blocks
    script_matches = re.findall(r'\"(?:image|photo_image|full_image|viewer_image)\":\s*\{\"uri\":\s*\"(https:[^\"]+?fbcdn\.net[^\"]+?)\"', html_text)
    script_matches += re.findall(r'\"(?:uri|src|preview_image)\":\s*\"(https:[^\"]+?fbcdn\.net[^\"]+?)\"', html_text)
    
    # 2. Match standard photo CDN URLs (t39.30808-6)
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

    # -------------------------------------------------------------
    # FAST PATH 1: Direct HTTP Request Engine (Under 1 Second)
    # -------------------------------------------------------------
    resolved_url = target_url
    try:
        session = requests.Session()
        res = session.get(target_url, headers=HEADERS, allow_redirects=True, timeout=8)
        resolved_url = res.url or target_url
        parse_html_for_photos(res.text, seen_ids, collected)

        # Also check mobile view payload for hidden album items
        if "www.facebook.com" in resolved_url:
            m_url = resolved_url.replace("www.facebook.com", "m.facebook.com")
            m_res = session.get(m_url, headers=HEADERS, allow_redirects=True, timeout=8)
            parse_html_for_photos(m_res.text, seen_ids, collected)
    except Exception as e:
        print("Fast HTTP extraction warning:", repr(e))

    # Agar 1 ya zyada photos mil chuki hain to foran return karein (No delay for Mobile App)
    if collected:
        return collected

    # -------------------------------------------------------------
    # FAST PATH 2: Video Fallback
    # -------------------------------------------------------------
    if 'res' in locals() and res.text:
        video_patterns = [
            (r'\"playable_url_quality_hd\":\s*\"(https:[^\"]+?)\"', "HD"),
            (r'\"browser_native_hd_url\":\s*\"(https:[^\"]+?)\"', "HD"),
            (r'\"playable_url\":\s*\"(https:[^\"]+?)\"', "SD"),
            (r'\"browser_native_sd_url\":\s*\"(https:[^\"]+?)\"', "SD")
        ]
        for pattern, quality in video_patterns:
            matches = re.findall(pattern, res.text)
            for raw_vid in matches:
                clean_vid = clean_fb_cdn_url(raw_vid)
                if clean_vid and "fbcdn.net" in clean_vid:
                    return [{
                        "url": clean_vid,
                        "type": "mp4",
                        "quality": f"Facebook Video ({quality})"
                    }]

    # -------------------------------------------------------------
    # PATH 3: Browserless Automation (Only if Direct Fetch fails)
    # -------------------------------------------------------------
    api_key = os.environ.get("BROWSERLESS_API_KEY", "2V9PPrLczaJ3bPxdca15920493ce5f1ff8d4201d5fe50a8af")
    ws_endpoint = f"wss://production-sfo.browserless.io?token={api_key}&stealth=true"

    try:
        with sync_playwright() as p:
            browser = None
            try:
                browser = p.chromium.connect_over_cdp(ws_endpoint, timeout=10000)
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
                    page.goto(resolved_url, wait_until="domcontentloaded", timeout=12000)
                    page.wait_for_timeout(1500)

                    clickable_photos = page.query_selector_all('a[href*="/photo"], a[href*="photo.php"]')
                    if clickable_photos:
                        try:
                            clickable_photos[0].click()
                            page.wait_for_timeout(800)
                            for _ in range(6):
                                page.keyboard.press("ArrowRight")
                                page.wait_for_timeout(300)
                        except Exception:
                            pass

                    parse_html_for_photos(page.content(), seen_ids, collected)
                except Exception as inner_e:
                    print("Browser inner error:", inner_e)
                finally:
                    browser.close()
    except Exception as e:
        print("Playwright connection error:", repr(e))

    # -------------------------------------------------------------
    # FINAL OPENGRAPH FALLBACK
    # -------------------------------------------------------------
    if not collected and 'res' in locals() and res.text:
        og_match = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', res.text)
        if og_match:
            og_clean = clean_fb_cdn_url(og_match.group(1))
            if is_valid_post_photo(og_clean):
                collected.append({"url": og_clean, "type": "jpg"})

    return collected

extract_all_fb_photos_sync = extract_fb_media
