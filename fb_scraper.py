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
        "t39.1997-6", "t39.1998-6" # Block user avatars and small icons
    ]
    return not any(b in lower for b in blocked) and url.startswith("https://")

def extract_fb_media(target_url: str):
    collected = []
    seen_ids = set()

    api_key = "2V9PPrLczaJ3bPxdca15920493ce5f1ff8d4201d5fe50a8af"
    ws_endpoint = f"wss://production-sfo.browserless.io?token={api_key}"

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(ws_endpoint)
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768}
        )

        page = context.new_page()

        try:
            desktop_url = target_url.replace("mbasic.facebook.com", "www.facebook.com").replace("m.facebook.com", "www.facebook.com")
            page.goto(desktop_url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(3000)

            content = page.content()

            # 1. Video Check
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
                    if clean_vid:
                        return [{"url": clean_vid, "type": "mp4", "quality": quality}]

            # 2. Open Photo Lightbox / Gallery Dialog if available
            photo_link = page.locator('a[href*="/photo/"], a[href*="photo.php"], a[href*="/photos/"]').first
            if photo_link.count() > 0:
                try:
                    page.evaluate("el => el.click()", photo_link.element_handle())
                except Exception:
                    photo_link.click(force=True, timeout=5000)
                
                page.wait_for_timeout(3000)

                # Loop through all slides using ArrowRight to capture every photo in the album
                for _ in range(12):
                    active_imgs = page.eval_on_selector_all(
                        'div[role="dialog"] img[data-visualcompletion="media-vc-image"], div[role="dialog"] img',
                        "elements => elements.map(e => e.src)"
                    )
                    
                    for src in active_imgs:
                        clean_img = clean_fb_cdn_url(src)
                        if is_valid_post_photo(clean_img):
                            match = re.search(r'/([0-9]{8,25})_[0-9]+_[0-9]+', clean_img) or \
                                    re.search(r'([0-9]{8,25}_[0-9]{8,25}_[no]\.(?:jpg|png|webp))', clean_img)
                            uid = match.group(1) if match else clean_img.split("?")[0].split("/")[-1]
                            if uid not in seen_ids:
                                seen_ids.add(uid)
                                collected.append({"url": clean_img, "type": "jpg"})

                    try:
                        page.keyboard.press("ArrowRight")
                        page.wait_for_timeout(1200)
                    except Exception:
                        break

            # 3. Comprehensive JSON / HTML Regex Fallback for all post images
            raw_uris = re.findall(r'\"uri\":\s*\"(https:[^\"]+?scontent[^\"]+?fbcdn\.net[^\"]+?)\"', content)
            for uri in raw_uris:
                clean_img = clean_fb_cdn_url(uri)
                if is_valid_post_photo(clean_img):
                    match = re.search(r'/([0-9]{8,25})_[0-9]+_[0-9]+', clean_img)
                    uid = match.group(1) if match else clean_img.split("?")[0].split("/")[-1]
                    if uid not in seen_ids:
                        seen_ids.add(uid)
                        collected.append({"url": clean_img, "type": "jpg"})

        except Exception as e:
            print("Scraper warning:", e)
        finally:
            browser.close()

    return collected

extract_all_fb_photos_sync = extract_fb_media
