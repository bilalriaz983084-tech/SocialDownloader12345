import os
import re
import html as html_lib
import urllib.parse
from playwright.sync_api import sync_playwright

def clean_fb_cdn_url(raw_url: str) -> str:
    """Clean and unescape Facebook CDN links so query signatures remain valid."""
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
    """Filter out UI icons, profile badges, emojis, and low-res thumbnails."""
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

def extract_fb_media(target_url: str):
    collected = []
    seen_ids = set()

    # Browserless.io remote endpoint configuration
    api_key = os.environ.get("BROWSERLESS_API_KEY", "2V9PPrLczaJ3bPxdca15920493ce5f1ff8d4201d5fe50a8af")
    ws_endpoint = f"wss://production-sfo.browserless.io?token={api_key}"

    try:
        with sync_playwright() as p:
            # Connect to Browserless remote Chromium instance
            browser = p.chromium.connect_over_cdp(ws_endpoint)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                viewport={"width": 1366, "height": 768}
            )
            page = context.new_page()

            # Dynamic listener to capture background CDN requests during user navigation
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
                desktop_url = target_url.replace("mbasic.facebook.com", "www.facebook.com").replace("m.facebook.com", "www.facebook.com")
                page.goto(desktop_url, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(2000)

                # Dismiss login popups or cookie consents if displayed
                try:
                    close_btn = page.query_selector('div[aria-label="Close"], [aria-label="Decline optional cookies"]')
                    if close_btn:
                        close_btn.click()
                except Exception:
                    pass

                # Scroll down to ensure main grid is loaded
                page.mouse.wheel(0, 1000)
                page.wait_for_timeout(1000)

                # Trigger Facebook Photo Theater Mode to fetch 5+ images via GraphQL
                clickable_photos = page.query_selector_all('a[href*="/photo"], a[href*="photo.php"]')
                if clickable_photos:
                    try:
                        clickable_photos[0].click()
                        page.wait_for_timeout(1200)

                        # Navigate right using keyboard arrow to stream all hidden album images
                        for _ in range(10):
                            page.keyboard.press("ArrowRight")
                            page.wait_for_timeout(350)
                    except Exception:
                        pass

                # DOM & Script Parsing Fallback
                content = page.content()

                script_matches = re.findall(r'\"(?:image|photo_image|full_image|viewer_image)\":\s*\{\"uri\":\s*\"(https:[^\"]+?scontent[^\"]+?fbcdn\.net[^\"]+?)\"', content)
                script_matches += re.findall(r'\"(?:uri|src|preview_image)\":\s*\"(https:[^\"]+?scontent[^\"]+?fbcdn\.net[^\"]+?)\"', content)

                for raw_uri in script_matches:
                    clean_img = clean_fb_cdn_url(raw_uri)
                    if is_valid_post_photo(clean_img):
                        match = re.search(r'/([0-9]{8,25})_', clean_img)
                        uid = match.group(1) if match else clean_img.split("?")[0].split("/")[-1]
                        if uid not in seen_ids:
                            seen_ids.add(uid)
                            collected.append({"url": clean_img, "type": "jpg"})

                # DOM img tag inspection
                imgs = page.eval_on_selector_all(
                    'div[role="main"] img, div[data-visualcompletion="media-vc-image"] img',
                    "elements => elements.map(e => e.src)"
                )
                for src in imgs:
                    clean_img = clean_fb_cdn_url(src)
                    if is_valid_post_photo(clean_img):
                        match = re.search(r'/([0-9]{8,25})_', clean_img)
                        uid = match.group(1) if match else clean_img.split("?")[0].split("/")[-1]
                        if uid not in seen_ids:
                            seen_ids.add(uid)
                            collected.append({"url": clean_img, "type": "jpg"})

                if collected:
                    return collected

                # Video Extraction Fallback (in case the post is a video)
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

            except Exception as e:
                print("Scraper inner error:", repr(e))
            finally:
                browser.close()

    except Exception as e:
        print("Browserless connection error:", repr(e))

    return collected

extract_all_fb_photos_sync = extract_fb_media
