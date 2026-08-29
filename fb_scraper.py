import re
import html as html_lib
import requests

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
        "p50x50", "p100x100", "p180x180", "s150x150", "s32x32", "s40x40", "s50x50", "safe_image.php", "profile", "cp1"
    ]
    if any(b in lower for b in blocked):
        return False
    return "oh=" in url or "oe=" in url

def extract_fb_media(target_url: str):
    photos_dict = {}

    try:
        # Facebook mobile URL banayein taake asani se HTML mil sakay
        mobile_url = re.sub(r'https?://(www\.)?facebook\.com', 'https://m.facebook.com', target_url)
        
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }

        response = requests.get(mobile_url, headers=headers, timeout=15)
        if response.status_code != 200:
            return []

        html_content = response.text

        # Regex ke zariye saare fbcdn image links extract karein
        raw_matches = re.findall(r'(https:[^"\'\s]+?fbcdn\.net[^"\'\s]+?(?:jpg|png|webp)[^"\'\s]*)', html_content)
        
        for raw_url in raw_matches:
            clean = clean_fb_cdn_url(raw_url)
            if is_valid_post_photo(clean):
                pid = extract_photo_id(clean)
                if pid:
                    if pid not in photos_dict:
                        photos_dict[pid] = clean
                else:
                    if clean not in photos_dict.values():
                        photos_dict[len(photos_dict)] = clean

    except Exception as e:
        print(f"Scraper error: {e}")

    return [{"url": url, "type": "jpg"} for url in photos_dict.values()]

extract_all_fb_photos_sync = extract_fb_media
