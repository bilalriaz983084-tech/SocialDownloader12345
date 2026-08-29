import os
import re
import urllib.parse
import requests
from bs4 import BeautifulSoup

def clean_fb_cdn_url(raw_url: str) -> str:
    if not raw_url:
        return ""
    clean = str(raw_url).strip()
    clean = clean.replace(r'\/', '/').replace('\\"', '"')
    clean = clean.replace(r'\u0026', '&').replace('&amp;', '&')
    clean = urllib.parse.unquote(clean)
    return clean.strip("\"'<> ,\\")

def is_valid_post_photo(url: str) -> bool:
    if not url or ("fbcdn.net" not in url and "facebook.com" not in url):
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

    session = requests.Session()
    
    # Facebook Bot User-Agent (Facebook bot ko login page nahi dikhata, direct meta tags deta hai)
    bot_headers = {
        "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    # Standard Mobile Browser Headers
    mobile_headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    # Step 1: Resolve short link (/share/p/ -> actual permalink)
    try:
        head_res = session.get(target_url, headers=mobile_headers, allow_redirects=True, timeout=10)
        resolved_url = head_res.url or target_url
    except Exception:
        resolved_url = target_url

    # Step 2: OpenGraph Extraction (Bypasses Login 100%)
    try:
        res = session.get(resolved_url, headers=bot_headers, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            
            # Check og:image (Full resolution original photo)
            for meta in soup.find_all("meta"):
                prop = meta.get("property", "").lower()
                name = meta.get("name", "").lower()
                if prop in ["og:image", "og:image:url", "og:image:secure_url"] or name in ["twitter:image", "thumbnail"]:
                    img_url = clean_fb_cdn_url(meta.get("content", ""))
                    if is_valid_post_photo(img_url) and img_url not in seen_urls:
                        seen_urls.add(img_url)
                        collected.append({"url": img_url, "type": "jpg", "thumbnail": img_url})

            if collected:
                return collected
    except Exception as e:
        print("[FB Bot Scraper Error]:", repr(e))

    # Step 3: Mobile JSON / HTML Stream Fallback (For Carousels / Albums)
    m_url = resolved_url.replace("www.facebook.com", "m.facebook.com").replace("mbasic.facebook.com", "m.facebook.com")
    try:
        res_m = session.get(m_url, headers=mobile_headers, timeout=12)
        if res_m.status_code == 200:
            content = res_m.text
            
            # Video fallback
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
                        collected.append({"url": clean_vid, "type": "mp4", "quality": quality, "thumbnail": ""})

            if collected:
                return collected

            # High-Res Image JSON patterns
            image_patterns = [
                r'\"full_size_image_url\":\s*\"(https:[^\"]+?)\"',
                r'\"image\":\{\"uri\":\s*\"(https:[^\"]+?)\"',
                r'\"uri\":\s*\"(https:[^\"]+?scontent[^\"]+?fbcdn\.net[^\"]+?)\"',
                r'\"preferred_thumbnail\":\{\"image\":\{\"uri\":\s*\"(https:[^\"]+?)\"'
            ]

            for pat in image_patterns:
                for uri in re.findall(pat, content):
                    clean_img = clean_fb_cdn_url(uri)
                    if is_valid_post_photo(clean_img):
                        match = re.search(r'/([0-9]{8,25})_[0-9]+_[0-9]+', clean_img)
                        uid = match.group(1) if match else clean_img.split("?")[0]
                        if uid not in seen_ids:
                            seen_ids.add(uid)
                            collected.append({"url": clean_img, "type": "jpg", "thumbnail": clean_img})

            if collected:
                return collected
    except Exception as e:
        print("[FB Mobile Fallback Error]:", repr(e))

    return collected

extract_all_fb_photos_sync = extract_fb_media
