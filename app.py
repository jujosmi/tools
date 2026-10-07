import base64
import binascii
import os
import re
import shutil
import tempfile
from pathlib import Path
from threading import Semaphore
from urllib.parse import urlparse

from flask import Flask, jsonify, render_template, request, send_file
import yt_dlp

app = Flask(__name__)

# Keep a small Render instance from being overwhelmed by concurrent conversions.
CONVERSION_SLOTS = Semaphore(2)

YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}

# Ordered fallback chain. These are public yt-dlp YouTube player clients with
# different current PO-token requirements. web_embedded only works for videos
# that allow embedding; web_safari may expose HLS; mweb uses the PO-token
# provider; tv is a final anonymous fallback.
YOUTUBE_CLIENTS = tuple(
    x.strip()
    for x in os.getenv(
        "YOUTUBE_CLIENTS",
        "web_embedded,web_safari,mweb,tv",
    ).split(",")
    if x.strip()
)


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
    return max(mp3s, key=lambda path: path.stat().st_mtime)


def maybe_write_cookie_file(folder: Path) -> Path | None:
    """Optionally load a cookies.txt file from a Render secret.

    Set YOUTUBE_COOKIES_B64 to a base64-encoded Netscape cookies.txt only when
    you have a legitimate reason to authenticate requests. Never commit cookies
    to GitHub or put them directly in source code.
    """
    encoded = os.getenv("YOUTUBE_COOKIES_B64", "").strip()
    if not encoded:
        return None

    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RuntimeError("YOUTUBE_COOKIES_B64 is not valid base64.") from exc

    if len(raw) > 2_000_000:
        raise RuntimeError("YOUTUBE_COOKIES_B64 is unexpectedly large.")

    cookie_file = folder / "cookies.txt"
    cookie_file.write_bytes(raw)
    return cookie_file


def build_options(work_dir: Path, client: str, cookie_file: Path | None) -> dict:
    out_template = str(work_dir / "%(id)s.%(ext)s")
    options = {
        "format": "bestaudio/best",
        "outtmpl": out_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": False,
        "restrictfilenames": True,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "extractor_args": {
            "youtube": {
                "player_client": [client],
            },
        },
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
    }

    # Only the clients that can use BgUtils should point at its HTTP provider.
    if client in {"mweb", "web", "web_safari", "ios"}:
        options["extractor_args"]["youtubepot-bgutilhttp"] = {
            "base_url": [os.getenv("BGUTIL_BASE_URL", "http://127.0.0.1:4416")],
        }

    if cookie_file is not None:
        options["cookiefile"] = str(cookie_file)

    return options


def download_mp3(url: str, work_dir: Path) -> tuple[Path, str, str]:
    cookie_file = maybe_write_cookie_file(work_dir)
    failures: list[tuple[str, str]] = []

    for client in YOUTUBE_CLIENTS:
        app.logger.info("Trying YouTube player client: %s", client)
        try:
            with yt_dlp.YoutubeDL(build_options(work_dir, client, cookie_file)) as ydl:
                info = ydl.extract_info(url, download=True)
                title = safe_filename(info.get("title") or "youtube-audio")
            return find_mp3(work_dir), title, client
        except Exception as exc:
            message = str(exc)
            failures.append((client, message))
            app.logger.warning("YouTube client %s failed: %s", client, message)

    summary = " | ".join(
        f"{client}: {msg[:300]}" for client, msg in failures
    )
    raise RuntimeError(f"All YouTube extraction clients failed. {summary}")


def friendly_error(exc: Exception) -> str:
    message = str(exc)
    lower = message.lower()

    if "sign in to confirm" in lower or "not a bot" in lower:
        return (
            "YouTube rejected requests from the converter's server. "
            "Multiple public extraction clients were tried, but this video "
            "or the server IP is still being challenged by YouTube."
        )
    if "private video" in lower:
        return "That video is private and cannot be converted."
    if "video unavailable" in lower or "this video is not available" in lower:
        return "That video is unavailable."
    if "age-restricted" in lower:
        return "That video is age-restricted and cannot be converted anonymously."
    if "only available for members" in lower or "members-only" in lower:
        return "That video is members-only and cannot be converted anonymously."

    return "Conversion failed. The video may be unavailable, restricted, or blocked by YouTube."


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/youtube-mp3")
def youtube_mp3_page():
    return render_template("index.html")


@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "service": "jujosmi-youtube-mp3",
        "yt_dlp": getattr(yt_dlp.version, "__version__", "unknown"),
        "youtube_clients": list(YOUTUBE_CLIENTS),
        "po_token_provider": os.getenv("BGUTIL_BASE_URL", "http://127.0.0.1:4416"),
    })


@app.post("/api/convert")
def convert():
    payload = request.get_json(silent=True) or {}
    url = str(payload.get("url", "")).strip()

    if not is_youtube_url(url):
        return jsonify({"error": "Enter a valid YouTube video URL."}), 400

    if not CONVERSION_SLOTS.acquire(blocking=False):
        return jsonify({"error": "The converter is busy. Please try again in a moment."}), 429

    temp_dir = Path(tempfile.mkdtemp(prefix="jujosmi-mp3-"))
    try:
        try:
            mp3_path, title, client = download_mp3(url, temp_dir)
            app.logger.info("YouTube conversion succeeded with client: %s", client)
        except Exception as exc:
            app.logger.exception("YouTube conversion failed after all fallbacks")
            return jsonify({"error": friendly_error(exc)}), 502

        response = send_file(
            mp3_path,
            as_attachment=True,
            download_name=f"{title}.mp3",
            mimetype="audio/mpeg",
            max_age=0,
        )

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
