import os
import json
import re
import urllib.parse
from playwright.sync_api import sync_playwright

def clean_fb_cdn_url(raw_url: str) -> str:
    if not raw_url:
        return ""
    clean = str(raw_url).strip()
    try:
        clean = clean.encode('utf-8').decode('unicode-escape')
    except Exception:
        pass
    clean = clean.replace(r'\/', '/')
    clean = urllib.parse.unquote(clean)
    clean = clean.replace(r'\u0026', '&').replace('&amp;', '&')
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

def load_cookies_to_context(context):
    cookie_files = ["cookies.json", "facebook_cookies.json"]
    for file_name in cookie_files:
        if os.path.exists(file_name):
            try:
                with open(file_name, "r", encoding="utf-8") as f:
                    cookies = json.load(f)
                    formatted_cookies = []
                    for c in cookies:
                        cookie_dict = {
                            "name": c.get("name"),
                            "value": c.get("value"),
                            "domain": c.get("domain", ".facebook.com"),
                            "path": c.get("path", "/")
                        }
                        if "expirationDate" in c:
                            cookie_dict["expires"] = c["expirationDate"]
                        formatted_cookies.append(cookie_dict)
                    context.add_cookies(formatted_cookies)
                    print(f"Successfully loaded cookies from {file_name}")
                    return True
            except Exception as e:
                print(f"Error loading {file_name}: {e}")
    return False

def extract_fb_media(target_url: str):
    collected = []
    seen_urls = set()
    seen_ids = set()

    api_key = "2V9PPrLczaJ3bPxdca15920493ce5f1ff8d4201d5fe50a8af"
    ws_endpoint = f"wss://production-sfo.browserless.io?token={api_key}"

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(ws_endpoint)
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768}
        )
        
        # Cookies load karein taake login session bypass ho jaye
        load_cookies_to_context(context)

        page = context.new_page()

        try:
            desktop_url = target_url.replace("mbasic.facebook.com", "www.facebook.com").replace("m.facebook.com", "www.facebook.com")
            page.goto(desktop_url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(3000)

            content = page.content()

            # 1. Video URLs check karein
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
                    if clean_vid and clean_vid not in seen_urls:
                        seen_urls.add(clean_vid)
                        collected.append({
                            "url": clean_vid,
                            "type": "mp4",
                            "quality": quality
                        })

            if collected:
                return collected

            # 2. Photos/Album Extractor
            photo_link = page.locator('a[href*="/photo/"], a[href*="photo.php"], a[href*="/photos/"]').first
            if photo_link.count() > 0:
                photo_link.click(timeout=4000)
                page.wait_for_timeout(3000)

                consecutive_no_new = 0
                for _ in range(30):
                    try:
                        page.keyboard.press("ArrowRight")
                    except Exception:
                        pass
                    
                    page.wait_for_timeout(1000)

                    active_imgs = page.eval_on_selector_all(
                        'div[role="dialog"] img, div[data-visualcompletion="media-vc-image"] img, img[data-visualcompletion="media-vc-image"]',
                        "elements => elements.map(e => e.src)"
                    )
                    
                    new_found = False
                    for src in active_imgs:
                        clean_img = clean_fb_cdn_url(src)
                        if is_valid_post_photo(clean_img):
                            match = re.search(r'/([0-9]{8,25})_[0-9]+_[0-9]+', clean_img) or \
                                    re.search(r'([0-9]{8,25}_[0-9]{8,25}_[no]\.(?:jpg|png|webp))', clean_img)
                            uid = match.group(1) if match else clean_img.split("?")[0].split("/")[-1]
                            if uid not in seen_ids:
                                seen_ids.add(uid)
                                collected.append({"url": clean_img, "type": "jpg"})
                                new_found = True

                    if not new_found:
                        consecutive_no_new += 1
                        if consecutive_no_new >= 5:
                            break
                    else:
                        consecutive_no_new = 0

            # 3. Static single-photo fallback
            if not collected:
                for uri in re.findall(r'\"uri\":\s*\"(https:[^\"]+?scontent[^\"]+?fbcdn\.net[^\"]+?)\"', content):
                    clean_img = clean_fb_cdn_url(uri)
                    if is_valid_post_photo(clean_img):
                        match = re.search(r'/([0-9]{8,25})_[0-9]+_[0-9]+', clean_img)
                        uid = match.group(1) if match else clean_img.split("?")[0]
                        if uid not in seen_ids:
                            seen_ids.add(uid)
                            collected.append({"url": clean_img, "type": "jpg"})

        except Exception as e:
            print("Scraper warning:", e)
        finally:
            browser.close()

    return collected

extract_all_fb_photos_sync = extract_fb_media
