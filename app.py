import os
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from threading import Semaphore

from flask import Flask, jsonify, render_template, request, send_file
import yt_dlp

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024  # Only a URL is expected.

# Keep simultaneous conversions bounded so one machine cannot be overwhelmed.
CONVERSION_SLOTS = Semaphore(2)

YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}


def is_youtube_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
        host = (parsed.hostname or "").lower().rstrip(".")
        return parsed.scheme in {"http", "https"} and host in YOUTUBE_HOSTS
    except ValueError:
        return False


def safe_filename(name: str) -> str:
    name = re.sub(r"[\x00-\x1f<>:\"/\\|?*]", "", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return (name or "youtube-audio")[:180]


def find_mp3(folder: Path) -> Path:
    mp3s = list(folder.glob("*.mp3"))
    if not mp3s:
        raise FileNotFoundError("Conversion finished but no MP3 file was produced.")
    return max(mp3s, key=lambda p: p.stat().st_mtime)


def download_mp3(url: str, work_dir: Path) -> tuple[Path, str]:
    out_template = str(work_dir / "%(id)s.%(ext)s")

    options = {
        "format": "bestaudio/best",
        "outtmpl": out_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        title = safe_filename(info.get("title") or "youtube-audio")

    return find_mp3(work_dir), title


@app.get("/")
def index():
    return render_template("index.html")

@app.get("/youtube-mp3")
def youtube_mp3_page():
    return render_template("index.html")


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "jujosmi-youtube-mp3"})


@app.post("/api/convert")
def convert():
    payload = request.get_json(silent=True) or {}
    url = str(payload.get("url", "")).strip()

    if not is_youtube_url(url):
        return jsonify({"error": "Enter a valid YouTube video URL."}), 400

    # Avoid queueing unbounded requests.
    if not CONVERSION_SLOTS.acquire(blocking=False):
        return jsonify({"error": "The converter is busy. Please try again in a moment."}), 429

    temp_dir = Path(tempfile.mkdtemp(prefix="jujosmi-mp3-"))
    try:
        try:
            mp3_path, title = download_mp3(url, temp_dir)
        except Exception as exc:
            app.logger.exception("YouTube conversion failed")
            return jsonify({
                "error": "Conversion failed. The video may be unavailable, restricted, or require a newer extractor."
            }), 502

        response = send_file(
            mp3_path,
            as_attachment=True,
            download_name=f"{title}.mp3",
            mimetype="audio/mpeg",
            max_age=0,
        )

        # Flask finishes reading the file before this callback executes.
        @response.call_on_close
        def cleanup():
            shutil.rmtree(temp_dir, ignore_errors=True)

        return response
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    finally:
        CONVERSION_SLOTS.release()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)
