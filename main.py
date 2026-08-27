import os
import re
import json
import urllib.parse
import asyncio
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor

import requests
import instaloader
import yt_dlp
import uvicorn

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from fb_scraper import extract_fb_media as fb_scraper_extract


# =========================================================
# APP
# =========================================================

app = FastAPI(
    title="Social Downloader Backend",
    version="20.0"
)


# =========================================================
# CORS
# =========================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# HEADERS
# =========================================================

DESKTOP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,"
        "image/avif,image/webp,"
        "*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Connection": "keep-alive",
}


# =========================================================
# INSTALOADER
# =========================================================

L = instaloader.Instaloader(
    download_pictures=False,
    download_videos=False,
    download_video_thumbnails=False,
    user_agent=DESKTOP_HEADERS["User-Agent"]
)


# =========================================================
# REQUEST MODEL
# =========================================================

class URLRequest(BaseModel):
    url: str
    is_audio: bool = False


# =========================================================
# LOGGER
# =========================================================

class QuietLogger:

    def debug(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass


# =========================================================
# DENO
# =========================================================

def find_deno():

    candidates = [
        os.environ.get("DENO_PATH"),
        os.environ.get("DENO"),

        os.path.expanduser(
            r"~\.deno\bin\deno.exe"
        ),

        r"C:\Program Files\deno\deno.exe",
        r"C:\Program Files (x86)\deno\deno.exe",
    ]

    try:

        deno = shutil.which("deno")

        if deno:
            candidates.insert(0, deno)

    except Exception:
        pass

    for path in candidates:

        if path and os.path.isfile(path):
            return os.path.abspath(path)

    return None


DENO_PATH = find_deno()


# =========================================================
# NODE
# =========================================================

def find_node():

    candidates = [
        os.environ.get("NODE_PATH"),
        os.environ.get("NODE"),

        r"C:\Program Files\nodejs\node.exe",
        r"C:\Program Files (x86)\nodejs\node.exe",
    ]

    try:

        node = shutil.which("node")

        if node:
            candidates.insert(0, node)

    except Exception:
        pass

    for path in candidates:

        if path and os.path.isfile(path):
            return os.path.abspath(path)

    return None


NODE_PATH = find_node()


# =========================================================
# STARTUP INFO
# =========================================================

print("======================================")
print(
    "yt-dlp version:",
    yt_dlp.version.__version__
)
print(
    "Deno:",
    DENO_PATH if DENO_PATH else "NOT FOUND"
)
print(
    "Node:",
    NODE_PATH if NODE_PATH else "NOT FOUND"
)
print("======================================")


# =========================================================
# YT-DLP BASE OPTIONS
# =========================================================

def get_ytdlp_runtime_options():

    options = {

        "http_headers": DESKTOP_HEADERS,

        "socket_timeout": 30,

        "retries": 5,

        "fragment_retries": 5,

        "extractor_retries": 3,

        "file_access_retries": 3,

        "logger": QuietLogger(),

        "quiet": True,

        "no_warnings": True,

        "noplaylist": True,

        "continuedl": False,

        "geo_bypass": True,

        "nocheckcertificate": False,

        "cachedir": False,

        "windowsfilenames": True,

        "restrictfilenames": False,

        "skip_download": True,

        "cookiefile": "youtube_cookies.txt",
    }

    if DENO_PATH:

        options["js_runtimes"] = {
            "deno": {
                "path": DENO_PATH
            }
        }

        options["remote_components"] = [
            "ejs:npm"
        ]

    elif NODE_PATH:

        options["js_runtimes"] = {
            "node": {
                "path": NODE_PATH
            }
        }

    return options


# =========================================================
# EXECUTOR & CLEANUP
# =========================================================

executor = ThreadPoolExecutor(
    max_workers=4
)

def remove_temp_file(filepath: str):
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception as e:
        print("Cleanup error:", repr(e))


# =========================================================
# URL RESOLVER
# =========================================================

def resolve_final_url(url: str):

    try:

        if "share_url=" in url:

            match = re.search(
                r"share_url=([^&]+)",
                url
            )

            if match:

                url = urllib.parse.unquote(
                    match.group(1)
                )

        session = requests.Session()

        response = session.get(
            url,
            headers=DESKTOP_HEADERS,
            allow_redirects=True,
            timeout=30
        )

        return response.url or url

    except Exception as e:

        print(
            "URL resolve warning:",
            repr(e)
        )

        return url


# =========================================================
# INSTAGRAM
# =========================================================

def extract_instagram_all_slides(url: str):

    media_items = []

    try:

        shortcode = None

        for tag in [
            "/p/",
            "/reel/",
            "/reels/"
        ]:

            if tag in url:

                shortcode = (
                    url.split(tag)[1]
                    .split("/")[0]
                    .split("?")[0]
                )

                break

        if shortcode:

            post = instaloader.Post.from_shortcode(
                L.context,
                shortcode
            )

            if post.typename == "GraphSidecar":

                for node in post.get_sidecar_nodes():

                    if node.is_video and node.video_url:

                        media_items.append({
                            "url": node.video_url,
                            "type": "mp4",
                            "thumbnail": node.display_url or post.url
                        })

                    elif node.display_url:

                        media_items.append({
                            "url": node.display_url,
                            "type": "jpg",
                            "thumbnail": node.display_url
                        })

            elif post.is_video and post.video_url:

                media_items.append({
                    "url": post.video_url,
                    "type": "mp4",
                    "thumbnail": post.url
                })

            elif post.url:

                media_items.append({
                    "url": post.url,
                    "type": "jpg",
                    "thumbnail": post.url
                })

            if media_items:
                return media_items

    except Exception as e:

        print(
            "Instagram error:",
            repr(e)
        )

    try:

        options = get_ytdlp_runtime_options()

        options.update({
            "skip_download": True,
            "ignoreerrors": True,
            "noplaylist": True,
        })

        with yt_dlp.YoutubeDL(options) as ydl:

            info = ydl.extract_info(
                url,
                download=False
            )

            if info:

                if info.get("entries"):

                    for entry in info["entries"]:

                        if not entry:
                            continue

                        media_url = entry.get("url")

                        if media_url:

                            media_items.append({
                                "url": media_url,
                                "type": (
                                    "mp4"
                                    if entry.get("ext") == "mp4"
                                    else "jpg"
                                ),
                                "thumbnail": entry.get("thumbnail") or info.get("thumbnail")
                            })

                elif info.get("url"):

                    media_items.append({
                        "url": info["url"],
                        "type": (
                            "mp4"
                            if info.get("ext") == "mp4"
                            else "jpg"
                        ),
                        "thumbnail": info.get("thumbnail")
                    })

    except Exception as e:

        print(
            "Instagram yt-dlp error:",
            repr(e)
        )

    return media_items


# =========================================================
# FACEBOOK
# =========================================================

async def extract_facebook_media(
    url: str,
    is_audio: bool = False
):

    resolved_url = resolve_final_url(url)

    print(
        "Targeting Facebook URL:",
        resolved_url
    )

    is_explicit_video = any(
        tag in resolved_url.lower()
        for tag in [
            "fb.watch",
            "/watch",
            "/videos/",
            "/reel/",
            "/reels/",
            "/share/v/",
            "/share/r/"
        ]
    )

    if is_explicit_video or is_audio:

        options = get_ytdlp_runtime_options()

        options.update({

            "skip_download": True,

            "ignoreerrors": True,

            "noplaylist": True,

        })

        try:

            with yt_dlp.YoutubeDL(options) as ydl:

                info = ydl.extract_info(
                    resolved_url,
                    download=False
                )

                if info:
                    thumb = info.get("thumbnail") or ""

                    if info.get("entries"):

                        items = []

                        for entry in info["entries"]:

                            if not entry:
                                continue

                            media_url = entry.get("url")

                            if media_url:

                                items.append({
                                    "url": media_url,
                                    "type": (
                                        "m4a"
                                        if is_audio
                                        else "mp4"
                                    ),
                                    "thumbnail": entry.get("thumbnail") or thumb
                                })

                        if items:
                            return items

                    if info.get("url"):

                        return [{
                            "url": info["url"],
                            "type": (
                                "m4a"
                                if is_audio
                                else "mp4"
                            ),
                            "thumbnail": thumb
                        }]

        except Exception as e:

            print(
                "Facebook yt-dlp error:",
                repr(e)
            )

    loop = asyncio.get_running_loop()

    raw_results = await loop.run_in_executor(
        executor,
        fb_scraper_extract,
        resolved_url
    )

    if raw_results and isinstance(raw_results, list):
        clean_items = []
        seen = set()
        for it in raw_results:
            u = it.get("url")
            if u and u not in seen:
                seen.add(u)
                clean_items.append(it)

        if len(clean_items) > 1 and all(x.get("type") == "mp4" for x in clean_items):
            return [clean_items[0]]

        return clean_items

    return raw_results or []


# =========================================================
# TIKTOK EXTRACTOR
# =========================================================

def extract_tiktok_media(url: str, is_audio: bool = False):
    print("\n======================================")
    print("TIKTOK EXTRACTION")
    print("URL:", url)
    print("Audio:", is_audio)
    print("======================================")

    clean_input_url = url.strip()

    try:
        api_url = f"https://www.tikwm.com/api/?url={clean_input_url}&hd=1"
        headers = {
            "User-Agent": DESKTOP_HEADERS["User-Agent"],
            "Referer": "https://www.tikwm.com/"
        }
        res = requests.get(api_url, headers=headers, timeout=20).json()

        if res.get("code") == 0 and "data" in res:
            data = res["data"]
            cover_img = data.get("cover") or data.get("origin_cover") or data.get("dynamic_cover")

            if "images" in data and isinstance(data["images"], list) and len(data["images"]) > 0:
                media_items = []
                for idx, img_url in enumerate(data["images"]):
                    if img_url and isinstance(img_url, str):
                        media_items.append({
                            "url": img_url,
                            "type": "jpg",
                            "thumbnail": img_url
                        })
                if media_items:
                    return media_items

            if is_audio:
                music_url = data.get("music") or data.get("music_info", {}).get("play")
                if music_url:
                    return [{
                        "url": music_url,
                        "type": "m4a",
                        "thumbnail": cover_img
                    }]

            video_url = data.get("hdplay") or data.get("play") or data.get("wmplay")
            if video_url:
                return [{
                    "url": video_url,
                    "type": "mp4",
                    "thumbnail": cover_img
                }]
    except Exception as e:
        print("TikTok TikWM error:", repr(e))

    return []


# =========================================================
# YOUTUBE API BACKEND
# =========================================================

def extract_youtube_api(video_id: str, is_audio: bool = False):
    instances = [
        "https://api.piped.privacydev.net",
        "https://pipedapi.leptons.xyz",
        "https://inv.tux.pizza",
        "https://invidious.nerdvpn.de",
        "https://vid.puffyan.us"
    ]

    for base in instances:
        try:
            if "piped" in base:
                api_url = f"{base}/streams/{video_id}"
                res = requests.get(api_url, headers=DESKTOP_HEADERS, timeout=4)
                if res.status_code == 200:
                    data = res.json()
                    thumb = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

                    if is_audio:
                        audio_streams = data.get("audioStreams", [])
                        if audio_streams:
                            return [{
                                "url": audio_streams[0].get("url"),
                                "type": "m4a",
                                "quality": f"Audio ({audio_streams[0].get('bitrate', 128)}kbps)",
                                "thumbnail": thumb
                            }]

                    results = []
                    seen_h = set()
                    streams = data.get("videoStreams", [])

                    for s in streams:
                        url = s.get("url")
                        quality_str = str(s.get("quality", ""))
                        height = s.get("height")
                        h_val = height if height else (int(re.sub(r"\D", "", quality_str)) if re.sub(r"\D", "", quality_str) else None)

                        if url and h_val in [1080, 720, 480, 360]:
                            if h_val not in seen_h:
                                seen_h.add(h_val)
                                results.append({
                                    "url": url,
                                    "type": "mp4",
                                    "quality": f"{h_val}p Full HD" if h_val == 1080 else f"{h_val}p HD" if h_val >= 720 else f"{h_val}p",
                                    "thumbnail": thumb
                                })

                    if results:
                        return sorted(results, key=lambda x: int(re.sub(r"\D", "", x["quality"].split()[0])), reverse=True)
            else:
                api_url = f"{base}/api/v1/videos/{video_id}"
                res = requests.get(api_url, headers=DESKTOP_HEADERS, timeout=4)
                if res.status_code == 200:
                    data = res.json()
                    thumb = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

                    if is_audio:
                        for f in data.get("adaptiveFormats", []):
                            if f.get("type", "").startswith("audio") and f.get("url"):
                                return [{
                                    "url": f["url"],
                                    "type": "m4a",
                                    "quality": "Audio (128kbps)",
                                    "thumbnail": thumb
                                }]

                    results = []
                    seen_h = set()
                    all_formats = data.get("formatStreams", []) + data.get("adaptiveFormats", [])
                    for f in all_formats:
                        h = re.sub(r"\D", "", f.get("resolution", "") or f.get("qualityLabel", ""))
                        if h.isdigit() and int(h) in [1080, 720, 480, 360]:
                            val = int(h)
                            if val not in seen_h and f.get("url"):
                                seen_h.add(val)
                                results.append({
                                    "url": f["url"],
                                    "type": "mp4",
                                    "quality": f"{val}p Full HD" if val == 1080 else f"{val}p HD" if val >= 720 else f"{val}p",
                                    "thumbnail": thumb
                                })

                    if results:
                        return sorted(results, key=lambda x: int(re.sub(r"\D", "", x["quality"].split()[0])), reverse=True)

        except Exception:
            continue

    return []


# =========================================================
# YOUTUBE MAIN EXTRACTOR
# =========================================================

def extract_youtube(url: str, is_audio: bool = False, host_url: str = ""):
    print("\n======================================")
    print("YOUTUBE EXTRACTION")
    print("URL:", url)
    print("Audio:", is_audio)
    print("======================================")

    clean_url = url.strip()
    
    match = re.search(r"(?:v=|\/|youtu\.be\/|embed\/|shorts\/)([a-zA-Z0-9_-]{11})", clean_url)
    video_id = match.group(1) if match else None

    clean_thumb = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else ""

    if video_id:
        clean_url = f"https://www.youtube.com/watch?v={video_id}"

        api_results = extract_youtube_api(video_id, is_audio)
        if api_results:
            return api_results

    options = get_ytdlp_runtime_options()

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(clean_url, download=False)

        if not info:
            return []

        results = []
        raw_thumb = info.get("thumbnail") or clean_thumb
        if ".webp" in raw_thumb:
            raw_thumb = raw_thumb.replace(".webp", ".jpg").replace("vi_webp", "vi")
        
        formats_list = info.get("formats", [])

        if is_audio:
            for f in reversed(formats_list):
                f_url = f.get("url")
                if f_url and f_url.startswith("http") and f.get("acodec") != "none" and f.get("vcodec") == "none":
                    abr = int(f.get("abr", 128)) if f.get("abr") else 128
                    return [{
                        "url": f_url,
                        "type": "m4a",
                        "quality": f"Audio ({abr}kbps)",
                        "thumbnail": raw_thumb
                    }]

        target_heights = [1080, 720, 480, 360]
        available_heights = set()

        for f in formats_list:
            h = f.get("height")
            if h in target_heights:
                available_heights.add(h)

        base_endpoint = host_url.rstrip("/") if host_url else "http://127.0.0.1:8000"
        encoded_url = urllib.parse.quote(clean_url)

        for h in sorted(list(available_heights), reverse=True):
            merged_download_url = f"{base_endpoint}/download?url={encoded_url}&quality={h}"
            results.append({
                "url": merged_download_url,
                "type": "mp4",
                "quality": f"{h}p Full HD" if h == 1080 else f"{h}p HD" if h >= 720 else f"{h}p",
                "thumbnail": raw_thumb
            })

        if not results:
            for h in target_heights:
                for f in reversed(formats_list):
                    f_url = f.get("url")
                    if f_url and f.get("height") == h:
                        results.append({
                            "url": f_url,
                            "type": "mp4",
                            "quality": f"{h}p HD" if h >= 720 else f"{h}p",
                            "thumbnail": raw_thumb
                        })
                        break

        return results

    except Exception as e:
        print("[ERROR] YouTube extraction error:", repr(e))
        return []


# =========================================================
# ROOT
# =========================================================

@app.get("/")
def root():

    return {

        "status":
            "Social Downloader Backend Online",

        "version":
            "20.0",

        "yt_dlp":
            yt_dlp.version.__version__,

        "deno":
            DENO_PATH
            if DENO_PATH
            else "NOT FOUND",

        "node":
            NODE_PATH
            if NODE_PATH
            else "NOT FOUND",

        "storage":
            "DYNAMIC AUTO-CLEANUP TEMP STORAGE",

        "downloadMode":
            "DIRECT & MERGED STREAM"
    }


# =========================================================
# MERGED VIDEO + AUDIO DOWNLOAD (FFMPEG)
# =========================================================

@app.get("/download")
async def download_merged_video(
    url: str,
    quality: str = "1080",
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    clean_url = urllib.parse.unquote(url.strip())
    temp_dir = tempfile.gettempdir()
    output_tmpl = os.path.join(temp_dir, "%(id)s_%(resolution)s.%(ext)s")

    format_str = f"bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best"

    ydl_opts = {
        "format": format_str,
        "outtmpl": output_tmpl,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "cookiefile": "youtube_cookies.txt",
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(clean_url, download=True)
            filename = ydl.prepare_filename(info)
            if not filename.endswith(".mp4"):
                filename = os.path.splitext(filename)[0] + ".mp4"

        if os.path.exists(filename):
            safe_title = re.sub(r'[\\/*?:"<>|]', "", info.get("title", "Video"))
            background_tasks.add_task(remove_temp_file, filename)
            return FileResponse(
                path=filename,
                media_type="video/mp4",
                filename=f"{safe_title}_{quality}p.mp4"
            )
        else:
            raise HTTPException(status_code=500, detail="File processing failed.")

    except Exception as e:
        print("Download/Merge Error:", repr(e))
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================
# MAIN EXTRACT
# =========================================================

@app.post("/extract")
async def extract_media(
    request: URLRequest,
    http_request: Request
):

    url = request.url.strip()

    if not url:

        raise HTTPException(
            status_code=400,
            detail="URL cannot be empty"
        )

    print("\n======================================")
    print("EXTRACT REQUEST:")
    print(url)
    print("Audio:", request.is_audio)
    print("======================================")

    media_items = []

    platform = "Social Media"
    url_lower = url.lower()
    host_url = str(http_request.base_url)

    if "instagram.com" in url_lower:

        platform = "Instagram"

        media_items = (
            extract_instagram_all_slides(
                url
            )
        )

    elif (

        "facebook.com" in url_lower

        or

        "fb.watch" in url_lower

    ):

        platform = "Facebook"

        media_items = (
            await extract_facebook_media(
                url,
                request.is_audio
            )
        )

    elif "tiktok.com" in url_lower:

        platform = "TikTok"

        media_items = (
            extract_tiktok_media(
                url,
                request.is_audio
            )
        )

    elif any(domain in url_lower for domain in ["youtube.com", "youtu.be", "m.youtube.com"]):

        platform = "YouTube"

        media_items = extract_youtube(
            url,
            request.is_audio,
            host_url
        )

    else:

        raise HTTPException(

            status_code=400,

            detail=(
                "Unsupported platform. "
                "Please use YouTube, Instagram, "
                "Facebook or TikTok."
            )

        )

    if not media_items:

        raise HTTPException(

            status_code=404,

            detail=(
                f"No downloadable media "
                f"found for this {platform} link."
            )

        )

    formats = []

    media_urls = []

    for idx, item in enumerate(
        media_items
    ):

        d_url = item.get("url")

        if not d_url:
            continue

        item_type = item.get(
            "type",
            "mp4"
        )

        quality = item.get(
            "quality"
        )

        if request.is_audio:

            extension = (

                item_type

                if item_type
                in ["mp3", "m4a"]

                else "m4a"

            )

        else:

            extension = item_type

        if not quality:

            if len(media_items) > 1:

                quality = (
                    f"Item {idx + 1}"
                )

            elif extension == "mp4":

                quality = "HD Video"

            elif extension == "jpg":

                quality = "HD Image"

            elif extension in [
                "mp3",
                "m4a"
            ]:

                quality = "Audio"

        formats.append({

            "quality":
                quality,

            "downloadUrl":
                d_url,

            "extension":
                extension

        })

        media_urls.append(
            d_url
        )

    if not formats:

        raise HTTPException(

            status_code=404,

            detail=(
                "Media was found but "
                "no valid download URL was returned."
            )

        )

    first_thumb = ""

    for item in media_items:
        t = item.get("thumbnail")
        if t and str(t).startswith("http") and not str(t).endswith(".mp4"):
            first_thumb = t
            break

    if first_thumb and ".webp" in first_thumb:
        first_thumb = first_thumb.replace(".webp", ".jpg").replace("vi_webp", "vi")

    if not first_thumb:
        for fmt in formats:
            if fmt["extension"] in ["jpg", "jpeg", "png"]:
                first_thumb = fmt["downloadUrl"]
                break

    if not first_thumb:
        if platform == "Facebook":
            first_thumb = "https://images.unsplash.com/photo-1611162617213-7d7a39e9b1d7?w=800&q=80"
        elif platform == "YouTube":
            first_thumb = "https://images.unsplash.com/photo-1611162618071-b39a2ec055fb?w=800&q=80"
        else:
            first_thumb = formats[0]["downloadUrl"]

    return {

        "status":
            "success",

        "title":
            f"{platform}_Download",

        "thumbnail":
            first_thumb,

        "sourcePlatform":
            platform,

        "total":
            len(formats),

        "media_urls":
            media_urls,

        "formats":
            formats,

        "serverStorage":
            False,

        "downloadMode":
            "direct",

        "fixedQuality": (
            "HD"
            if platform == "TikTok"
            and formats
            and all(f.get("extension") == "jpg" for f in formats)
            else None
        ),

        "isCarousel": (
            platform == "TikTok"
            and len(formats) > 1
            and all(f.get("extension") == "jpg" for f in formats)
        )

    }


# =========================================================
# START SERVER
# =========================================================

if __name__ == "__main__":

    uvicorn.run(

        app,

        host="0.0.0.0",

        port=8000,

        log_level="info"

    )
