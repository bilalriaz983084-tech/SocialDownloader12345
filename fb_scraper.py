import re
import urllib.parse
from playwright.sync_api import sync_playwright

def clean_fb_cdn_url(raw_url: str) -> str:
    if not raw_url:
        return ""
    clean = str(raw_url).strip()
    # Safe JSON string unescape
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
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768}
        )
        page = context.new_page()

        try:
            desktop_url = target_url.replace("mbasic.facebook.com", "www.facebook.com").replace("m.facebook.com", "www.facebook.com")
            page.goto(desktop_url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(2500)

            # Cookie / Login popup dismiss
            try:
                close_btn = page.locator('div[role="dialog"] div[aria-label="Close"], div[aria-label="Decline optional cookies"]').first
                if close_btn.count() > 0:
                    close_btn.click(timeout=2000)
            except Exception:
                pass

            content = page.content()

            # 1. Video URLs check (HD / SD)
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

            # 2. Photos / Carousel Extraction
            photo_link = page.locator('a[href*="/photo/"], a[href*="photo.php"], a[href*="/photos/"]').first
            if photo_link.count() > 0:
                try:
                    photo_link.click(timeout=3000)
                    page.wait_for_timeout(1500)
                except Exception:
                    pass

                consecutive_no_new = 0
                for _ in range(30):
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
                        if consecutive_no_new >= 3:
                            break
                    else:
                        consecutive_no_new = 0

                    page.keyboard.press("ArrowRight")
                    page.wait_for_timeout(500)

            # 3. Static fallback
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
            context.close()
            browser.close()

    return collected

extract_all_fb_photos_sync = extract_fb_media
