import os
import re
import sys
import json
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
    if not url or "fbcdn.net" not in url:
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

    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    session = requests.Session()

    # Step 1: Follow full redirects
    try:
        head_res = session.get(target_url, headers=headers, allow_redirects=True, timeout=12)
        resolved_url = head_res.url or target_url
    except Exception:
        resolved_url = target_url

    # Step 2: Use mbasic endpoint (Bypasses Login Wall for Photos)
    mbasic_url = resolved_url.replace("www.facebook.com", "mbasic.facebook.com").replace("m.facebook.com", "mbasic.facebook.com")
    if "mbasic.facebook.com" not in mbasic_url:
        mbasic_url = re.sub(r'https?://[^/]+', 'https://mbasic.facebook.com', resolved_url)

    try:
        res = session.get(mbasic_url, headers=headers, timeout=12)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            
            # Find photo page links if this is a container post
            photo_links = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/photo.php" in href or "/photos/" in href:
                    full_link = urllib.parse.urljoin("https://mbasic.facebook.com", href)
                    photo_links.append(full_link)

            # If photo links found, extract full size from them
            for plink in photo_links[:10]:
                try:
                    p_res = session.get(plink, headers=headers, timeout=8)
                    if p_res.status_code == 200:
                        p_soup = BeautifulSoup(p_res.text, "html.parser")
                        for img in p_soup.find_all("img"):
                            src = img.get("src", "")
                            clean_img = clean_fb_cdn_url(src)
                            if is_valid_post_photo(clean_img):
                                match = re.search(r'/([0-9]{8,25})_[0-9]+_[0-9]+', clean_img)
                                uid = match.group(1) if match else clean_img.split("?")[0]
                                if uid not in seen_ids:
                                    seen_ids.add(uid)
                                    collected.append({"url": clean_img, "type": "jpg"})
                except Exception:
                    continue

            # Also check direct img tags on post page
            if not collected:
                for img in soup.find_all("img"):
                    src = img.get("src", "")
                    clean_img = clean_fb_cdn_url(src)
                    if is_valid_post_photo(clean_img):
                        match = re.search(r'/([0-9]{8,25})_[0-9]+_[0-9]+', clean_img)
                        uid = match.group(1) if match else clean_img.split("?")[0]
                        if uid not in seen_ids:
                            seen_ids.add(uid)
                            collected.append({"url": clean_img, "type": "jpg"})

            if collected:
                return collected
    except Exception as e:
        print("[FB MBasic Error]:", repr(e))

    # Step 3: Desktop Regex Fallback (For single images/videos)
    desktop_url = resolved_url.replace("mbasic.facebook.com", "www.facebook.com").replace("m.facebook.com", "www.facebook.com")
    try:
        desktop_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        }
        res_desk = session.get(desktop_url, headers=desktop_headers, timeout=12)
        if res_desk.status_code == 200:
            content = res_desk.text

            image_patterns = [
                r'\"full_size_image_url\":\s*\"(https:[^\"]+?)\"',
                r'\"image\":\{\"uri\":\s*\"(https:[^\"]+?)\"',
                r'\"uri\":\s*\"(https:[^\"]+?scontent[^\"]+?fbcdn\.net[^\"]+?)\"'
            ]

            for pat in image_patterns:
                for uri in re.findall(pat, content):
                    clean_img = clean_fb_cdn_url(uri)
                    if is_valid_post_photo(clean_img):
                        match = re.search(r'/([0-9]{8,25})_[0-9]+_[0-9]+', clean_img)
                        uid = match.group(1) if match else clean_img.split("?")[0]
                        if uid not in seen_ids:
                            seen_ids.add(uid)
                            collected.append({"url": clean_img, "type": "jpg"})

            if collected:
                return collected
    except Exception as e:
        print("[FB Desktop Fallback Error]:", repr(e))

    return collected

extract_all_fb_photos_sync = extract_fb_media
