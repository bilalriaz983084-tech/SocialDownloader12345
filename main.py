import os
import re
import json
import urllib.parse
import asyncio
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor

import requests
import yt_dlp
import uvicorn

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from fb_scraper import extract_fb_media as fb_scraper_extract

app = FastAPI(title="Social Downloader Backend", version="20.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

DESKTOP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Connection": "keep-alive",
}

class URLRequest(BaseModel):
    url: str
    is_audio: bool = False

class QuietLogger:
    def debug(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass

def find_deno():
    candidates = [os.environ.get("DENO_PATH"), os.environ.get("DENO"), r"C:\Program Files\deno\deno.exe"]
    try:
        deno = shutil.which("deno")
        if deno: candidates.insert(0, deno)
    except Exception: pass
    for path in candidates:
        if path and os.path.isfile(path): return os.path.abspath(path)
    return None

DENO_PATH = find_deno()

def find_node():
    candidates = [os.environ.get("NODE_PATH"), os.environ.get("NODE"), r"C:\Program Files\nodejs\node.exe"]
    try:
        node = shutil.which("node")
        if node: candidates.insert(0, node)
    except Exception: pass
    for path in candidates:
        if path and os.path.isfile(path): return os.path.abspath(path)
    return None

NODE_PATH = find_node()

def get_ytdlp_runtime_options():
    options = {
        "http_headers": DESKTOP_HEADERS,
        "socket_timeout": 30,
        "retries": 5,
        "logger": QuietLogger(),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "geo_bypass": True,
        "skip_download": True,
    }
    if DENO_PATH:
        options["js_runtimes"] = {"deno": {"path": DENO_PATH}}
    elif NODE_PATH:
        options["js_runtimes"] = {"node": {"path": NODE_PATH}}
    return options

executor = ThreadPoolExecutor(max_workers=4)

def remove_temp_file(filepath: str):
    try:
        if os.path.exists(filepath): os.remove(filepath)
    except Exception as e:
        print("Cleanup error:", repr(e))

def resolve_final_url(url: str):
    try:
        if "share_url=" in url:
            match = re.search(r"share_url=([^&]+)", url)
            if match: url = urllib.parse.unquote(match.group(1))
        session = requests.Session()
        response = session.get(url, headers=DESKTOP_HEADERS, allow_redirects=True, timeout=30)
        return response.url or url
    except Exception as e:
        return url

def extract_instagram_all_slides(url: str):
    media_items = []
    try:
        options = get_ytdlp_runtime_options()
        options.update({"skip_download": True, "ignoreerrors": True, "noplaylist": True})
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
            if info:
                if info.get("entries"):
                    for entry in info["entries"]:
                        if not entry: continue
                        media_url = entry.get("url")
                        if media_url:
                            media_items.append({
                                "url": media_url,
                                "type": "mp4" if entry.get("ext") == "mp4" else "jpg",
                                "thumbnail": entry.get("thumbnail") or info.get("thumbnail")
                            })
                elif info.get("url"):
                    media_items.append({
                        "url": info["url"],
                        "type": "mp4" if info.get("ext") == "mp4" else "jpg",
                        "thumbnail": info.get("thumbnail")
                    })
    except Exception as e:
        print("Instagram yt-dlp error:", repr(e))
    return media_items

async def extract_facebook_media(url: str, is_audio: bool = False):
    resolved_url = resolve_final_url(url)
    options = get_ytdlp_runtime_options()
    options.update({"skip_download": True, "ignoreerrors": True, "noplaylist": True})
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(resolved_url, download=False)
            if info:
                thumb = info.get("thumbnail") or ""
                if info.get("entries"):
                    items = []
                    for entry in info["entries"]:
                        if not entry: continue
                        media_url = entry.get("url")
                        if media_url:
                            items.append({
                                "url": media_url,
                                "type": "m4a" if is_audio else "mp4",
                                "thumbnail": entry.get("thumbnail") or thumb
                            })
                    if items: return items
                if info.get("url"):
                    return [{
                        "url": info["url"],
                        "type": "m4a" if is_audio else "mp4",
                        "thumbnail": thumb
                    }]
    except Exception as e:
        print("Facebook yt-dlp error:", repr(e))

    loop = asyncio.get_running_loop()
    raw_results = await loop.run_in_executor(executor, fb_scraper_extract, resolved_url)
    return raw_results or []

def extract_tiktok_media(url: str, is_audio: bool = False):
    try:
        api_url = f"https://www.tikwm.com/api/?url={url.strip()}&hd=1"
        res = requests.get(api_url, headers={"User-Agent": DESKTOP_HEADERS["User-Agent"]}, timeout=20).json()
        if res.get("code") == 0 and "data" in res:
            data = res["data"]
            cover_img = data.get("cover") or data.get("origin_cover")
            if "images" in data and isinstance(data["images"], list) and len(data["images"]) > 0:
                return [{"url": img, "type": "jpg", "thumbnail": img} for img in data["images"] if img]
            if is_audio and data.get("music"):
                return [{"url": data["music"], "type": "m4a", "thumbnail": cover_img}]
            video_url = data.get("hdplay") or data.get("play")
            if video_url:
                return [{"url": video_url, "type": "mp4", "thumbnail": cover_img}]
    except Exception as e:
        print("TikTok error:", repr(e))
    return []

def extract_youtube(url: str, is_audio: bool = False, host_url: str = ""):
    clean_url = url.strip()
    match = re.search(r"(?:v=|\/|youtu\.be\/|embed\/|shorts\/)([a-zA-Z0-9_-]{11})", clean_url)
    video_id = match.group(1) if match else None
    if video_id: clean_url = f"https://www.youtube.com/watch?v={video_id}"

    options = get_ytdlp_runtime_options()
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(clean_url, download=False)
        if not info: return []
        results = []
        raw_thumb = info.get("thumbnail") or ""
        formats_list = info.get("formats", [])
        
        if is_audio:
            for f in reversed(formats_list):
                f_url = f.get("url")
                if f_url and f.get("acodec") != "none" and f.get("vcodec") == "none":
                    return [{"url": f_url, "type": "m4a", "quality": "Audio (128kbps)", "thumbnail": raw_thumb}]

        base_endpoint = host_url.rstrip("/") if host_url else "http://127.0.0.1:8000"
        encoded_url = urllib.parse.quote(clean_url)
        for h in [1080, 720, 480, 360]:
            if any(f.get("height") == h for f in formats_list):
                results.append({
                    "url": f"{base_endpoint}/download?url={encoded_url}&quality={h}",
                    "type": "mp4",
                    "quality": f"{h}p HD" if h >= 720 else f"{h}p",
                    "thumbnail": raw_thumb
                })
        return results
    except Exception as e:
        print("YouTube error:", repr(e))
        return []

@app.get("/")
def root():
    return {"status": "Online", "version": "20.0"}

@app.get("/download")
async def download_video(url: str, quality: str = "1080", background_tasks: BackgroundTasks = BackgroundTasks()):
    clean_url = urllib.parse.unquote(url.strip())
    temp_dir = tempfile.gettempdir()
    output_tmpl = os.path.join(temp_dir, "%(id)s_%(resolution)s.%(ext)s")
    ydl_opts = {
        "format": f"bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/best[height<={quality}]/best",
        "outtmpl": output_tmpl,
        "merge_output_format": "mp4",
        "quiet": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(clean_url, download=True)
            filename = ydl.prepare_filename(info)
            if not filename.endswith(".mp4"): filename = os.path.splitext(filename)[0] + ".mp4"
        if os.path.exists(filename):
            background_tasks.add_task(remove_temp_file, filename)
            return FileResponse(path=filename, media_type="video/mp4", filename=f"video_{quality}p.mp4")
        raise HTTPException(status_code=500, detail="Failed")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/extract")
async def extract_media(request: URLRequest, http_request: Request):
    url = request.url.strip()
    if not url: raise HTTPException(status_code=400, detail="Empty URL")
    
    media_items = []
    platform = "Social Media"
    url_lower = url.lower()
    host_url = str(http_request.base_url)

    if "instagram.com" in url_lower:
        platform = "Instagram"
        media_items = extract_instagram_all_slides(url)
    elif "facebook.com" in url_lower or "fb.watch" in url_lower:
        platform = "Facebook"
        media_items = await extract_facebook_media(url, request.is_audio)
    elif "tiktok.com" in url_lower:
        platform = "TikTok"
        media_items = extract_tiktok_media(url, request.is_audio)
    elif any(d in url_lower for d in ["youtube.com", "youtu.be"]):
        platform = "YouTube"
        media_items = extract_youtube(url, request.is_audio, host_url)
    else:
        raise HTTPException(status_code=400, detail="Unsupported platform")

    if not media_items: raise HTTPException(status_code=404, detail="No media found")

    formats = [{"quality": "HD", "downloadUrl": item["url"], "extension": item.get("type", "mp4")} for item in media_items if item.get("url")]
    return {"status": "success", "title": f"{platform}_Download", "thumbnail": media_items[0].get("thumbnail", ""), "sourcePlatform": platform, "formats": formats}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
