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
                title = info.get('title', 'Facebook_Video')
                if video_url:
                    collected.append({
                        "url": video_url,
                        "type": "mp4",
                        "quality": "HD"
                    })
                    return collected
    except Exception as e:
        print("yt-dlp video extraction fallback:", e)

    # 2. Agar video na mile ya photo/post ho toh requests aur regex se HTML parse karein (Serverless Friendly)
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9"
        }
        response = requests.get(clean_target_url, headers=headers, timeout=15)
        content = response.text

        # Video patterns check karein HTML mein se agar yt-dlp fail ho jaye
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

        # Static Photos fallback from HTML source
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

    return collected

# Compatibility alias
extract_all_fb_photos_sync = extract_fb_media
