import re
import html as html_lib
import time
import requests
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
    blocked = [
        "giphy", "emg1", "emoji", "rsrc.php", "cp0", 
        "p50x50", "p100x100", "p180x180", "s150x150", "s32x32", "s40x40", "s50x50", 
        "safe_image.php", "profile", "cp1", "static.xx"
    ]
    return not any(b in lower for b in blocked) and ("oh=" in url or "oe=" in url)

def resolve_share_url(share_url: str) -> str:
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        }
        res = requests.get(share_url, headers=headers, allow_redirects=True, timeout=10)
        return res.url
    except Exception:
        return share_url

def extract_fb_media(target_url: str):
    photos_dict = {}
    videos_list = []
    seen_video_urls = set()

    # Step 1: Resolve short link
    resolved_url = resolve_share_url(target_url)
    clean_target = resolved_url.replace("m.facebook.com", "www.facebook.com").replace("mbasic.facebook.com", "www.facebook.com")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled"
            ]
        )

        # Anti-Bot Evasion Profile
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            extra_http_headers={
                "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-fetch-dest": "document",
                "sec-fetch-mode": "navigate",
                "sec-fetch-site": "none",
                "sec-fetch-user": "?1",
                "upgrade-insecure-requests": "1"
            }
        )

        # Optional: Add dummy or test Facebook cookie to bypass generic server auth blocks
        # Agar aapke paas koi burner/dummy FB account hai to 'c_user' aur 'xs' cookie yahan daal sakte hain
        fb_c_user = os.getenv("FB_C_USER", "")
        fb_xs = os.getenv("FB_XS", "")
        if fb_c_user and fb_xs:
            context.add_cookies([
                {"name": "c_user", "value": fb_c_user, "domain": ".facebook.com", "path": "/"},
                {"name": "xs", "value": fb_xs, "domain": ".facebook.com", "path": "/"}
            ])

        page = context.new_page()

        try:
            # Step 2: Navigate with full network idle wait
            page.goto(clean_target, wait_until="domcontentloaded", timeout=40000)
            time.sleep(3.5)

            # Step 3: Handle login/cookie banners
            for sel in ['div[aria-label="Close"]', 'div[aria-label="close"]', 'div[data-testid="cookie-policy-manage-dialog-accept-button"]']:
                try:
                    btn = page.locator(sel).first
                    if btn.count() > 0 and btn.is_visible():
                        btn.click(force=True)
                except Exception:
                    pass

            # Step 4: Extract JSON Blocks from script tags
            html_content = page.content()

            # Video extraction
            video_patterns = [
                (r'\"playable_url_quality_hd\":\s*\"(https:[^\"]+?)\"', "HD Video"),
                (r'\"browser_native_hd_url\":\s*\"(https:[^\"]+?)\"', "HD Video"),
                (r'\"playable_url\":\s*\"(https:[^\"]+?)\"', "SD Video"),
                (r'\"browser_native_sd_url\":\s*\"(https:[^\"]+?)\"', "SD Video")
            ]
            for pattern, quality in video_patterns:
                matches = re.findall(pattern, html_content)
                for raw_vid in matches:
                    clean_v = clean_fb_cdn_url(raw_vid)
                    if clean_v and clean_v not in seen_video_urls and "fbcdn.net" in clean_v:
                        seen_video_urls.add(clean_v)
                        videos_list.append({"url": clean_v, "type": "mp4", "quality": quality})

            # Photo extraction (Catches all high-resolution URLs)
            raw_photos = re.findall(r'\"uri\":\s*\"(https:[^\"]+?fbcdn\.net[^\"]+?)\"', html_content)
            if not raw_photos:
                raw_photos = re.findall(r'(https:[^"\'\s]+?fbcdn\.net[^"\'\s]+?(?:jpg|png|webp)[^"\'\s]*)', html_content)

            for raw_u in raw_photos:
                clean = clean_fb_cdn_url(raw_u)
                if is_valid_post_photo(clean):
                    pid = extract_photo_id(clean)
                    if pid:
                        if pid not in photos_dict:
                            photos_dict[pid] = clean
                        else:
                            curr = photos_dict[pid]
                            if ("ctp=s" in curr or "s590x590" in curr or "p320x320" in curr) and ("mx1170" in clean or "dst-jpg" in clean):
                                photos_dict[pid] = clean

            # Step 5: DOM Fallback
            if not photos_dict and not videos_list:
                for img in page.locator('img[src*="fbcdn.net"]').all():
                    try:
                        src = img.get_attribute("src")
                        if src and is_valid_post_photo(src):
                            clean = clean_fb_cdn_url(src)
                            pid = extract_photo_id(clean)
                            if pid and pid not in photos_dict:
                                photos_dict[pid] = clean
                    except Exception:
                        pass

        except Exception as e:
            print(f"Playwright extraction exception: {e}")
        finally:
            browser.close()

    if photos_dict:
        return [{"url": u, "type": "jpg"} for u in photos_dict.values()]

    if videos_list:
        return videos_list

    return []

extract_all_fb_photos_sync = extract_fb_media
