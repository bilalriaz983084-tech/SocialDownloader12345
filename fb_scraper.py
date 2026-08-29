import os
import re
import html as html_lib
import urllib.parse
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
}

BROWSERLESS_API_KEY = os.environ.get("BROWSERLESS_API_KEY", "2V9PPrLczaJ3bPxdca15920493ce5f1ff8d4201d5fe50a8af")


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
    script_matches = re.findall(r'\"(?:image|photo_image|full_image|viewer_image)\":\s*\{\"uri\":\s*\"(https:[^\"]+?fbcdn\.net[^\"]+?)\"', html_text)
    script_matches += re.findall(r'\"(?:uri|src|preview_image)\":\s*\"(https:[^\"]+?fbcdn\.net[^\"]+?)\"', html_text)
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


def parse_html_for_videos(html_text: str, seen_urls: set, collected: list):
    video_patterns = [
        (r'\"playable_url_quality_hd\":\s*\"(https:[^\"]+?)\"', "HD"),
        (r'\"browser_native_hd_url\":\s*\"(https:[^\"]+?)\"', "HD"),
        (r'\"playable_url\":\s*\"(https:[^\"]+?)\"', "SD"),
        (r'\"browser_native_sd_url\":\s*\"(https:[^\"]+?)\"', "SD"),
        (r'\"preferred_video_delivery_uri\":\s*\"(https:[^\"]+?)\"', "HD"),
        (r'\"subtitled_video_uri\":\s*\"(https:[^\"]+?)\"', "SD")
    ]

    for pattern, quality in video_patterns:
        matches = re.findall(pattern, html_text)
        for raw_vid in matches:
            clean_vid = clean_fb_cdn_url(raw_vid)
            if clean_vid and "fbcdn.net" in clean_vid and clean_vid not in seen_urls and "bytestart" not in clean_vid:
                seen_urls.add(clean_vid)
                collected.append({
                    "url": clean_vid,
                    "type": "mp4",
                    "quality": f"Facebook Video ({quality})"
                })


# =========================================================
# 1. SEPARATE PHOTO EXTRACTOR
# =========================================================
def extract_fb_photos(target_url: str):
    collected = []
    seen_ids = set()

    session = requests.Session()
    resolved_url = target_url

    try:
        res = session.get(target_url, headers=HEADERS, allow_redirects=True, timeout=6)
        resolved_url = res.url or target_url
        parse_html_for_photos(res.text, seen_ids, collected)

        if "www.facebook.com" in resolved_url:
            m_url = resolved_url.replace("www.facebook.com", "m.facebook.com")
            m_res = session.get(m_url, headers=HEADERS, allow_redirects=True, timeout=6)
            parse_html_for_photos(m_res.text, seen_ids, collected)
    except Exception as e:
        print("Direct photo fetch warning:", repr(e))

    if len(collected) >= 2:
        return collected

    # Browserless Cloud REST API (Multi-photo & dynamic load fallback)
    browserless_api = f"https://production-sfo.browserless.io/content?token={BROWSERLESS_API_KEY}&stealth=true"
    try:
        payload = {"url": resolved_url, "waitForTimeout": 3000}
        b_res = requests.post(browserless_api, json=payload, headers={"Content-Type": "application/json"}, timeout=12)
        if b_res.status_code == 200:
            parse_html_for_photos(b_res.text, seen_ids, collected)
    except Exception as e:
        print("Browserless Photos Error:", repr(e))

    # OpenGraph Fallback
    if not collected and 'res' in locals() and res.text:
        og_match = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', res.text)
        if og_match:
            og_url = clean_fb_cdn_url(og_match.group(1))
            if is_valid_post_photo(og_url):
                collected.append({"url": og_url, "type": "jpg"})

    return collected


# =========================================================
# 2. SEPARATE VIDEO EXTRACTOR
# =========================================================
def extract_fb_videos(target_url: str):
    collected = []
    seen_urls = set()

    session = requests.Session()
    resolved_url = target_url

    try:
        res = session.get(target_url, headers=HEADERS, allow_redirects=True, timeout=6)
        resolved_url = res.url or target_url
        parse_html_for_videos(res.text, seen_urls, collected)
    except Exception as e:
        print("Direct video fetch warning:", repr(e))

    if collected:
        return collected

    # Browserless Cloud REST API (Reels & Watch Video fallback)
    browserless_api = f"https://production-sfo.browserless.io/content?token={BROWSERLESS_API_KEY}&stealth=true"
    try:
        payload = {"url": resolved_url, "waitForTimeout": 3500}
        b_res = requests.post(browserless_api, json=payload, headers={"Content-Type": "application/json"}, timeout=14)
        if b_res.status_code == 200:
            parse_html_for_videos(b_res.text, seen_urls, collected)
    except Exception as e:
        print("Browserless Video Error:", repr(e))

    return collected


# =========================================================
# 3. COMBINED MEDIA EXTRACTOR (Used in main.py)
# =========================================================
def extract_fb_media(target_url: str):
    # Step 1: Pehle strictly photos dhoondega
    photos = extract_fb_photos(target_url)
    if photos:
        return photos

    # Step 2: Agar photos na hon to video dhoondega
    videos = extract_fb_videos(target_url)
    if videos:
        return videos

    return []


extract_all_fb_photos_sync = extract_fb_media
