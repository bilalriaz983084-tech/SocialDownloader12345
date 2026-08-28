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
        "_a.jpg", "_a.png", "ads", "sponsor", "banner", "external",
        "t39.1997-6", "t39.1998-6"
    ]
    return not any(b in lower for b in blocked) and url.startswith("https://")

def load_cookies_to_context(context):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cookie_files = [
        os.path.join(base_dir, "facebook_cookies.json"),
        os.path.join(base_dir, "cookies.json"),
        "facebook_cookies.json",
        "cookies.json"
    ]
    for file_path in cookie_files:
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
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
                    return True
            except Exception:
                pass
    return False

def extract_fb_media(target_url: str):
    collected = []
    seen_urls = set()
    seen_ids = set()

    api_key = "2V9PPrLczaJ3bPxdca15920493ce5f1ff8d4201d5fe50a8af"
    ws_endpoint = f"wss://production-sfo.browserless.io?token={api_key}"

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(ws_endpoint)
        except Exception:
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
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768}
        )
        
        load_cookies_to_context(context)
        page = context.new_page()

        try:
            desktop_url = target_url.replace("mbasic.facebook.com", "www.facebook.com").replace("m.facebook.com", "www.facebook.com")
            page.goto(desktop_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(4000)

            # Scroll down to force Facebook to load all album images in DOM
            for _ in range(4):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1500)

            content = page.content()

            # 1. Comprehensive regex to grab ALL scontent high-res image URIs from raw script/JSON data in page
            all_uris = re.findall(r'\"(?:image|photo_image|full_image|uri)\":\s*\"(https:[^\"]+?scontent[^\"]+?fbcdn\.net[^\"]+?)\"', content)
            all_uris += re.findall(r'(https:\/\/[^\s<>"]+?scontent[^\s<>"]+?fbcdn\.net[^\s<>"]+?\.(?:jpg|png|webp)[^\s<>"]*)', content)

            for raw_uri in all_uris:
                clean_img = clean_fb_cdn_url(raw_uri)
                if is_valid_post_photo(clean_img):
                    match = re.search(r'/([0-9]{8,25})_[0-9]+_[0-9]+', clean_img) or \
                            re.search(r'([0-9]{8,25}_[0-9]{8,25}_[no]\.(?:jpg|png|webp))', clean_img)
                    uid = match.group(1) if match else clean_img.split("?")[0].split("/")[-1]
                    if uid not in seen_ids:
                        seen_ids.add(uid)
                        collected.append({"url": clean_img, "type": "jpg"})

            # 2. Lightbox slide check if direct regex missed anything
            photo_link = page.locator('a[href*="/photo/"], a[href*="photo.php"], a[href*="/photos/"]').first
            if photo_link.count() > 0:
                try:
                    page.evaluate("el => el.click()", photo_link.element_handle())
                    page.wait_for_timeout(3000)
                    for _ in range(20):
                        active_imgs = page.eval_on_selector_all(
                            'div[role="dialog"] img',
                            "elements => elements.map(e => e.src)"
                        )
                        for src in active_imgs:
                            clean_img = clean_fb_cdn_url(src)
                            if is_valid_post_photo(clean_img):
                                uid = clean_img.split("?")[0].split("/")[-1]
                                if uid not in seen_ids:
                                    seen_ids.add(uid)
                                    collected.append({"url": clean_img, "type": "jpg"})
                        page.keyboard.press("ArrowRight")
                        page.wait_for_timeout(1000)
                except Exception:
                    pass

        except Exception as e:
            print("Scraper warning:", e)
        finally:
            browser.close()

    return collected

extract_all_fb_photos_sync = extract_fb_media
