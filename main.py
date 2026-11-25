import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

import yt_dlp
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from mutagen.id3 import ID3, ID3NoHeaderError, TIT2, TPE1, TALB, TCON, APIC
from pydantic import BaseModel

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Ganti dengan domain Vercel-mu nanti
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUT_DIR = Path(tempfile.gettempdir()) / "audio_output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

jobs_db = {}

class InfoRequest(BaseModel):
    url: str

class ProcessRequest(BaseModel):
    url: str
    metadata: dict
    bitrate: str

# --- FUNGSI YANG DIPERBARUI UNTUK MENANGANI BOT DETECTION ---
def get_ydl_opts(extra_opts=None):
    """Mengembalikan opsi yt-dlp dengan pengaturan anti-blokir."""
    opts = {
        "quiet": True,
        "noplaylist": True,
        "format": "bestaudio",
        "nocheckcertificate": True,
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web_safari"], 
                "player_skip": ["webpage", "configs"],
            }
        },
    }
    
    # Coba gunakan cookies dari environment variable jika ada
    cookies_b64 = os.environ.get("YT_COOKIES")
    if cookies_b64:
        import base64
        cookie_file = Path(tempfile.gettempdir()) / "cookies.txt"
        cookie_file.write_bytes(base64.b64decode(cookies_b64))
        opts["cookiefile"] = str(cookie_file)
        print("Menggunakan file cookies untuk otentikasi.")
    
    if extra_opts:
        opts.update(extra_opts)
    return opts

def sanitize_filename(name):
    name = re.sub(r'[\\/*?:"<>|]', "", str(name))
    return name.strip()[:150] or "audio"

def get_video_info(url):
    with yt_dlp.YoutubeDL(get_ydl_opts()) as ydl:
        return ydl.extract_info(url, download=False)

def get_best_audio_format(info):
    formats = info.get("formats", [])
    audio_formats = [f for f in formats if f.get("acodec") != "none" and f.get("vcodec") == "none"]
    if not audio_formats: return None
    return max(audio_formats, key=lambda f: (f.get("abr") or f.get("tbr") or 0))

def download_audio(url, temp_dir):
    opts = get_ydl_opts({
        "outtmpl": str(temp_dir / "%(id)s.%(ext)s"),
        "writethumbnail": True,
    })
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        requested = info.get("requested_downloads") or []
        source = requested[0].get("filepath") if requested else ydl.prepare_filename(info)
    return Path(source), info

def find_thumbnail(video_id, temp_dir):
    for ext in [".jpg", ".jpeg", ".png", ".webp", ".avif"]:
        candidate = temp_dir / f"{video_id}{ext}"
        if candidate.exists(): return candidate
    return None

def convert_cover_to_png(cover, temp_dir):
    if not cover: return None
    output = temp_dir / "cover.png"
    subprocess.run(["ffmpeg", "-y", "-i", str(cover), "-frames:v", "1", str(output)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return output if output.exists() else None

def convert_to_mp3(source, output, bitrate, metadata):
    cmd = [
        "ffmpeg", "-y", "-i", str(source), "-map", "0:a:0", "-vn",
        "-c:a", "libmp3lame", "-b:a", f"{bitrate}k", "-id3v2_version", "3",
        "-metadata", f"title={metadata.get('title', '')}",
        "-metadata", f"artist={metadata.get('artist', '')}",
        "-metadata", f"album={metadata.get('album', '')}",
        "-metadata", f"genre={metadata.get('genre', '')}", str(output)
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def write_metadata(output, cover, metadata):
    try: tags = ID3(output)
    except ID3NoHeaderError: tags = ID3()
    
    for tag in ["TIT2", "TPE1", "TALB", "TCON", "APIC"]: tags.delall(tag)
    
    tags.add(TIT2(encoding=3, text=metadata.get('title', '')))
    tags.add(TPE1(encoding=3, text=metadata.get('artist', '')))
    tags.add(TALB(encoding=3, text=metadata.get('album', '')))
    tags.add(TCON(encoding=3, text=metadata.get('genre', '')))
    
    if cover and cover.exists():
        with open(cover, "rb") as img:
            tags.add(APIC(encoding=3, mime="image/png", type=3, desc="cover", data=img.read()))
    tags.save(output, v2_version=3)

def process_audio_task(job_id: str, url: str, metadata: dict, bitrate: str):
    temp_dir = Path(tempfile.mkdtemp(prefix="job_"))
    try:
        jobs_db[job_id].update({"status": "downloading", "stage": "Mengunduh audio...", "progress": 10})
        source, info = download_audio(url, temp_dir)
        
        jobs_db[job_id].update({"status": "converting", "stage": "Mengonversi MP3...", "progress": 50})
        filename = sanitize_filename(metadata["title"])
        output = OUTPUT_DIR / f"{job_id}_{filename}.mp3"
        
        convert_to_mp3(source, output, bitrate, metadata)
        
        jobs_db[job_id].update({"status": "tagging", "stage": "Menulis metadata...", "progress": 80})
        cover = convert_cover_to_png(find_thumbnail(info.get("id"), temp_dir), temp_dir)
        write_metadata(output, cover, metadata)
        
        jobs_db[job_id].update({
            "status": "completed", "stage": "Selesai!", "progress": 100,
            "result": {
                "fileName": f"{filename}.mp3",
                "fileSize": output.stat().st_size,
                "bitrate": bitrate,
                "downloadUrl": f"/api/jobs/{job_id}/download"
            }
        })
    except Exception as e:
        jobs_db[job_id].update({"status": "failed", "error": str(e)})
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

@app.get("/")
def health_check():
    return {"status": "ok", "message": "API is running"}

@app.post("/api/info")
def get_info(req: InfoRequest):
    try:
        info = get_video_info(req.url)
        best_audio = get_best_audio_format(info)
        bitrate = best_audio.get("abr") or best_audio.get("tbr") if best_audio else None
        
        suggested = 192
        if bitrate:
            if bitrate < 96: suggested = 128
            elif bitrate < 160: suggested = 192
            elif bitrate < 224: suggested = 256
            else: suggested = 320

        return {
            "videoId": info.get("id"),
            "title": info.get("title", "Unknown"),
            "artist": info.get("artist") or info.get("uploader") or "Unknown",
            "album": info.get("album") or "",
            "genre": info.get("genre") or "",
            "duration": info.get("duration"),
            "thumbnailUrl": info.get("thumbnail"),
            "audio": {
                "codec": best_audio.get("acodec") if best_audio else None,
                "bitrate": bitrate,
                "sampleRate": best_audio.get("asr") if best_audio else None,
                "suggestedBitrate": suggested
            },
            "availableBitrates": [128, 192, 256, 320]
        }
    except Exception as e:
        print(f"ERROR di /api/info: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/process")
def start_process(req: ProcessRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    jobs_db[job_id] = {"jobId": job_id, "status": "queued", "progress": 0, "stage": "Menunggu antrean..."}
    background_tasks.add_task(process_audio_task, job_id, req.url, req.metadata, req.bitrate)
    return {"jobId": job_id, "status": "queued"}

@app.get("/api/jobs/{job_id}")
def get_status(job_id: str):
    if job_id not in jobs_db:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs_db[job_id]

@app.get("/api/jobs/{job_id}/download")
def download_file(job_id: str):
    if job_id not in jobs_db or jobs_db[job_id]["status"] != "completed":
        raise HTTPException(status_code=400, detail="File not ready")
    
    file_name = jobs_db[job_id]["result"]["fileName"]
    file_path = OUTPUT_DIR / f"{job_id}_{file_name}"
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on server")
        
    return FileResponse(path=file_path, filename=file_name, media_type="audio/mpeg")
