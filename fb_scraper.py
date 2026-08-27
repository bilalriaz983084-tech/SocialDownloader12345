import re
import urllib.parse
import requests
import yt_dlp

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
        "_a.jpg", "_a.png", "ads", "sponsor", "banner", "external"
    ]
    return not any(b in lower for b in blocked) and url.startswith("https://")

def extract_fb_media(target_url: str):
    collected = []
    seen_urls = set()
    seen_ids = set()

    clean_target_url = target_url.replace("mbasic.facebook.com", "www.facebook.com").replace("m.facebook.com", "www.facebook.com")

    # 1. Pehle yt-dlp se Facebook Video extract karne ki koshish karein
    try:
        ydl_opts = {
            'format': 'best',
            'socket_timeout': 15,
            'quiet': True,
            'no_warnings': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(clean_target_url, download=False)
            if info:
                video_url = info.get('url')
                if video_url:
                    collected.append({
                        "url": video_url,
                        "type": "mp4",
                        "quality": "HD"
                    })
                    return collected
    except Exception as e:
        print("yt-dlp video extraction fallback:", e)

    # 2. Requests se HTML parse karein (Redirects allow karke aur mbasic version bhi try karke)
    urls_to_try = [clean_target_url]
    if "share/p/" in target_url or "share/v/" in target_url:
        urls_to_try.insert(0, clean_target_url.replace("www.facebook.com", "mbasic.facebook.com"))

    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5"
    }

    content = ""
    for u in urls_to_try:
        try:
            resp = requests.get(u, headers=headers, allow_redirects=True, timeout=15)
            if resp.status_code == 200 and len(resp.text) > 1000:
                content = resp.text
                break
        except Exception:
            continue

    if not content:
        return collected

    try:
        # Video patterns check karein
        video_patterns = [
            r'\"playable_url_quality_hd\":\s*\"(https:[^\"]+?)\"',
            r'\"browser_native_hd_url\":\s*\"(https:[^\"]+?)\"',
            r'\"playable_url\":\s*\"(https:[^\"]+?)\"',
            r'\"browser_native_sd_url\":\s*\"(https:[^\"]+?)\"'
        ]

        for pattern in video_patterns:
            matches = re.findall(pattern, content)
            for raw_vid in matches:
                clean_vid = clean_fb_cdn_url(raw_vid)
                if clean_vid and clean_vid not in seen_urls:
                    seen_urls.add(clean_vid)
                    collected.append({
                        "url": clean_vid,
                        "type": "mp4",
                        "quality": "HD"
                    })

        if collected:
            return collected

        # 3. Aggressive Photo & Image Patterns Extractor (mbasic aur standard dono ke liye)
        img_matches = re.findall(r'https?://[^\s<>"]+?scontent[^\s<>"]+?fbcdn\.net[^\s<>"]+?', content)
        
        for raw_img in img_matches:
            clean_img = clean_fb_cdn_url(raw_img)
            # '&amp;' ya extra html entities saaf karein
            clean_img = clean_img.split('&amp;')[0].split('"')[0]
            if is_valid_post_photo(clean_img):
                match = re.search(r'/([0-9]{8,25})_[0-9]+_[0-9]+', clean_img) or \
                        re.search(r'([0-9]{8,25}_[0-9]{8,25}_[no]\.(?:jpg|png|webp))', clean_img)
                uid = match.group(1) if match else clean_img.split("?")[0].split("/")[-1]
                if uid not in seen_ids:
                    seen_ids.add(uid)
                    collected.append({"url": clean_img, "type": "jpg"})

    except Exception as e:
        print("Scraper warning:", e)

    return collected

# Compatibility alias
extract_all_fb_photos_sync = extract_fb_media
