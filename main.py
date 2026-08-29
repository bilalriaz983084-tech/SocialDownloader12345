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

# =========================================================
# SAFE IMPORT FOR FB SCRAPER
# =========================================================
try:
    from fb_scraper import extract_fb_media as fb_scraper_extract
except ImportError:
    def fb_scraper_extract(url: str):
        return []

# =========================================================
# APP & CORS
# =========================================================
app = FastAPI(title="Social Downloader Backend", version="20.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================================
# HEADERS & SESSIONS
# =========================================================
DESKTOP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Connection": "keep-alive",
}

L = instaloader.Instaloader(
    download_pictures=False,
    download_videos=False,
    download_video_thumbnails=False,
    user_agent=DESKTOP_HEADERS["User-Agent"],
)

class URLRequest(BaseModel):
    url: str
    is_audio: bool = False

class QuietLogger:
    def debug(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass

# =========================================================
# RUNTIME DETECTORS
# =========================================================
def find_deno():
    candidates = [
        os.environ.get("DENO_PATH"),
        os.environ.get("DENO"),
        os.path.expanduser(r"~\.deno\bin\deno.exe"),
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

DENO_PATH = find_deno()
NODE_PATH = find_node()

print("======================================")
print("yt-dlp version:", yt_dlp.version.__version__)
print("Deno:", DENO_PATH if DENO_PATH else "NOT FOUND")
print("Node:", NODE_PATH if NODE_PATH else "NOT FOUND")
print("======================================")

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
    }
    if DENO_PATH:
        options["js_runtimes"] = {"deno": {"path": DENO_PATH}}
        options["remote_components"] = ["ejs:npm"]
    elif NODE_PATH:
        options["js_runtimes"] = {"node": {"path": NODE_PATH}}
    return options

executor = ThreadPoolExecutor(max_workers=8)

def remove_temp_file(filepath: str):
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception as e:
        print("Cleanup error:", repr(e))

def resolve_final_url(url: str):
    try:
        if "share_url=" in url:
            match = re.search(r"share_url=([^&]+)", url)
            if match:
                url = urllib.parse.unquote(match.group(1))
        session = requests.Session()
        response = session.get(url, headers=DESKTOP_HEADERS, allow_redirects=True, timeout=20)
        return response.url or url
    except Exception as e:
        print("URL resolve warning:", repr(e))
        return url

# =========================================================
# PLATFORM EXTRACTORS
# =========================================================
def extract_instagram_all_slides(url: str):
    media_items = []
    try:
        shortcode = None
        for tag in ["/p/", "/reel/", "/reels/"]:
            if tag in url:
                shortcode = url.split(tag)[1].split("/")[0].split("?")[0]
                break
        if shortcode:
            post = instaloader.Post.from_shortcode(L.context, shortcode)
            if post.typename == "GraphSidecar":
                for node in post.get_sidecar_nodes():
                    if node.is_video and node.video_url:
                        media_items.append({"url": node.video_url, "type": "mp4", "thumbnail": node.display_url or post.url})
                    elif node.display_url:
                        media_items.append({"url": node.display_url, "type": "jpg", "thumbnail": node.display_url})
            elif post.is_video and post.video_url:
                media_items.append({"url": post.video_url, "type": "mp4", "thumbnail": post.url})
            elif post.url:
                media_items.append({"url": post.url, "type": "jpg", "thumbnail": post.url})
            if media_items:
                return media_items
    except Exception as e:
        print("Instagram error:", repr(e))

    try:
        options = get_ytdlp_runtime_options()
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
            if info:
                entries = info.get("entries") or [info]
                for entry in entries:
                    if not entry: continue
                    media_url = entry.get("url")
                    if media_url:
                        media_items.append({
                            "url": media_url,
                            "type": "mp4" if entry.get("ext") == "mp4" else "jpg",
                            "thumbnail": entry.get("thumbnail") or info.get("thumbnail")
                        })
    except Exception as e:
        print("Instagram yt-dlp error:", repr(e))

    return media_items

async def extract_facebook_media(url: str, is_audio: bool = False):
    resolved_url = resolve_final_url(url)
    is_explicit_video = any(
        tag in resolved_url.lower()
        for tag in ["fb.watch", "/watch", "/videos/", "/reel/", "/reels/", "/share/v/", "/share/r/"]
    )
    if is_explicit_video or is_audio:
        options = get_ytdlp_runtime_options()
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(resolved_url, download=False)
                if info:
                    thumb = info.get("thumbnail") or ""
                    if info.get("entries"):
                        items = []
                        for entry in info["entries"]:
                            if entry and entry.get("url"):
                                items.append({
                                    "url": entry["url"],
                                    "type": "m4a" if is_audio else "mp4",
                                    "thumbnail": entry.get("thumbnail") or thumb,
                                })
                        if items: return items
                    if info.get("url"):
                        return [{"url": info["url"], "type": "m4a" if is_audio else "mp4", "thumbnail": thumb}]
        except Exception as e:
            print("Facebook yt-dlp error:", repr(e))

    loop = asyncio.get_running_loop()
    raw_results = await loop.run_in_executor(executor, fb_scraper_extract, resolved_url)
    if raw_results and isinstance(raw_results, list):
        clean_items = []
        seen = set()
        for it in raw_results:
            u = it.get("url")
            if u and u not in seen:
                seen.add(u)
                clean_items.append(it)
        return clean_items
    return []

def extract_tiktok_media(url: str, is_audio: bool = False):
    clean_input_url = url.strip()
    try:
        api_url = f"https://www.tikwm.com/api/?url={clean_input_url}&hd=1"
        res = requests.get(api_url, headers=DESKTOP_HEADERS, timeout=20).json()
        if res.get("code") == 0 and "data" in res:
            data = res["data"]
            cover_img = data.get("cover") or data.get("origin_cover") or data.get("dynamic_cover")

            if "images" in data and isinstance(data["images"], list) and len(data["images"]) > 0:
                return [{"url": img, "type": "jpg", "thumbnail": img} for img in data["images"] if img]

            if is_audio:
                music_url = data.get("music") or data.get("music_info", {}).get("play")
                if music_url:
                    return [{"url": music_url, "type": "m4a", "thumbnail": cover_img}]

            video_url = data.get("hdplay") or data.get("play") or data.get("wmplay")
            if video_url:
                return [{"url": video_url, "type": "mp4", "thumbnail": cover_img}]
    except Exception as e:
        print("TikTok TikWM error:", repr(e))
    return []

def extract_youtube(url: str, is_audio: bool = False, host_url: str = ""):
    clean_url = url.strip()
    match = re.search(r"(?:v=|\/|youtu\.be\/|embed\/|shorts\/)([a-zA-Z0-9_-]{11})", clean_url)
    video_id = match.group(1) if match else None
    clean_thumb = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else ""

    if video_id:
        clean_url = f"https://www.youtube.com/watch?v={video_id}"

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
                        return [{"url": f_url, "type": "m4a", "quality": f"Audio ({abr}kbps)", "thumbnail": raw_thumb}]

            target_heights = [1080, 720, 480, 360]
            available_heights = set(f.get("height") for f in formats_list if f.get("height") in target_heights)

            base_endpoint = host_url.rstrip("/") if host_url else "http://127.0.0.1:8000"
            encoded_url = urllib.parse.quote(clean_url)

            for h in sorted(list(available_heights), reverse=True):
                merged_download_url = f"{base_endpoint}/download?url={encoded_url}&quality={h}"
                results.append({
                    "url": merged_download_url,
                    "type": "mp4",
                    "quality": f"{h}p Full HD" if h == 1080 else f"{h}p HD" if h >= 720 else f"{h}p",
                    "thumbnail": raw_thumb,
                })
            return results
    except Exception as e:
        print("[ERROR] YouTube extraction error:", repr(e))
        return []

# =========================================================
# API ROUTES
# =========================================================
@app.get("/")
def root():
    return {
        "status": "Social Downloader Backend Online",
        "version": "20.0",
        "yt_dlp": yt_dlp.version.__version__,
        "deno": DENO_PATH if DENO_PATH else "NOT FOUND",
        "node": NODE_PATH if NODE_PATH else "NOT FOUND",
    }

@app.get("/download")
async def download_merged_video(
    background_tasks: BackgroundTasks,
    url: str,
    quality: str = "1080"
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
    }

    try:
        loop = asyncio.get_running_loop()

        def process_download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(clean_url, download=True)
                fn = ydl.prepare_filename(info)
                if not fn.endswith(".mp4"):
                    fn = os.path.splitext(fn)[0] + ".mp4"
                return fn, info.get("title", "Video")

        filename, title = await loop.run_in_executor(executor, process_download)

        if os.path.exists(filename):
            safe_title = re.sub(r'[\\/*?:"<>|]', "", title)
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

@app.post("/extract")
async def extract_media(request: URLRequest, http_request: Request):
    url = request.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL cannot be empty")

    platform = "Social Media"
    url_lower = url.lower()
    host_url = str(http_request.base_url)
    loop = asyncio.get_running_loop()

    if "instagram.com" in url_lower:
        platform = "Instagram"
        media_items = await loop.run_in_executor(executor, extract_instagram_all_slides, url)
    elif "facebook.com" in url_lower or "fb.watch" in url_lower:
        platform = "Facebook"
        media_items = await extract_facebook_media(url, request.is_audio)
    elif "tiktok.com" in url_lower:
        platform = "TikTok"
        media_items = await loop.run_in_executor(executor, extract_tiktok_media, url, request.is_audio)
    elif any(domain in url_lower for domain in ["youtube.com", "youtu.be", "m.youtube.com"]):
        platform = "YouTube"
        media_items = await loop.run_in_executor(executor, extract_youtube, url, request.is_audio, host_url)
    else:
        raise HTTPException(status_code=400, detail="Unsupported platform.")

    if not media_items:
        raise HTTPException(status_code=404, detail=f"No downloadable media found for this {platform} link.")

    formats = []
    media_urls = []
    for idx, item in enumerate(media_items):
        d_url = item.get("url")
        if not d_url:
            continue
        item_type = item.get("type", "mp4")
        quality = item.get("quality")
        if request.is_audio:
            extension = item_type if item_type in ["mp3", "m4a"] else "m4a"
        else:
            extension = item_type

        if not quality:
            if len(media_items) > 1:
                quality = f"Item {idx + 1}"
            elif extension == "mp4":
                quality = "HD Video"
            elif extension == "jpg":
                quality = "HD Image"
            elif extension in ["mp3", "m4a"]:
                quality = "Audio"

        formats.append({"quality": quality, "downloadUrl": d_url, "extension": extension})
        media_urls.append(d_url)

    if not formats:
        raise HTTPException(status_code=404, detail="Media was found but no valid download URL was returned.")

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
        first_thumb = formats[0]["downloadUrl"]

    return {
        "status": "success",
        "title": f"{platform}_Download",
        "thumbnail": first_thumb,
        "sourcePlatform": platform,
        "total": len(formats),
        "media_urls": media_urls,
        "formats": formats,
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
