import os
import re
import json
import urllib.parse
import requests

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
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document"
    })

    # 1. Resolve redirect to get the true Facebook URL
    resolved_url = target_url
    try:
        r = session.get(target_url, allow_redirects=True, timeout=12)
        resolved_url = r.url or target_url
    except Exception as e:
        print("[FB Resolve Warning]:", repr(e))

    print(f"[FB Engine] Resolved URL: {resolved_url}")

    # 2. Extract Post ID / Fbid from URL
    post_id = None
    patterns = [
        r'/posts/([0-9]+)',
        r'/photos/[^/]+/([0-9]+)',
        r'fbid=([0-9]+)',
        r'story_fbid=([0-9]+)',
        r'/permalink/([0-9]+)',
        r'/p/([a-zA-Z0-9_-]+)'
    ]
    for p in patterns:
        m = re.search(p, resolved_url)
        if m:
            post_id = m.group(1)
            break

    # 3. Direct HTML / Script Blob Scanner
    try:
        res = session.get(resolved_url, timeout=15)
        content = res.text

        # 3a. High Quality Photo Matchers in JSON script payloads
        img_regexes = [
            r'\"image\":\{\"uri\":\"(https:[^\"]+?)\"',
            r'\"full_size_image_url\":\"(https:[^\"]+?)\"',
            r'\"preferred_thumbnail\":\{\"image\":\{\"uri\":\"(https:[^\"]+?)\"',
            r'\"uri\":\"(https:[^\"]+?scontent[^\"]+?fbcdn\.net[^\"]+?)\"',
            r'\"large_share_image\":\{\"uri\":\"(https:[^\"]+?)\"',
            r'<meta property=\"og:image\" content=\"(https:[^\"]+?)\"'
        ]

        for reg in img_regexes:
            matches = re.findall(reg, content)
            for raw_u in matches:
                clean_u = clean_fb_cdn_url(raw_u)
                if is_valid_post_photo(clean_u) and clean_u not in seen_urls:
                    seen_urls.add(clean_u)
                    collected.append({
                        "url": clean_u,
                        "type": "jpg",
                        "thumbnail": clean_u
                    })

        if collected:
            print(f"[FB Engine] Found {len(collected)} items via HTML payload")
            return collected

    except Exception as e:
        print("[FB HTML Scan Error]:", repr(e))

    # 4. Mobile Endpoint Fallback (m.facebook.com)
    try:
        mobile_url = resolved_url.replace("www.facebook.com", "m.facebook.com")
        mob_headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 11; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
        }
        res_mob = session.get(mobile_url, headers=mob_headers, timeout=12)
        mob_text = res_mob.text

        for raw_u in re.findall(r'\"(https://[^\"]+?fbcdn\.net[^\"]+?)\"', mob_text):
            clean_u = clean_fb_cdn_url(raw_u)
            if is_valid_post_photo(clean_u) and clean_u not in seen_urls:
                seen_urls.add(clean_u)
                collected.append({
                    "url": clean_u,
                    "type": "jpg",
                    "thumbnail": clean_u
                })

        if collected:
            print(f"[FB Engine] Found {len(collected)} items via Mobile Endpoint")
            return collected

    except Exception as e:
        print("[FB Mobile Error]:", repr(e))

    return collected

extract_all_fb_photos_sync = extract_fb_media
