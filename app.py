import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import requests
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename

app = Flask(__name__)

SOCIALKIT_ENDPOINT = "https://api.socialkit.dev/v2/youtube/download"
SOCIALKIT_STATUS = "https://api.socialkit.dev/v2/downloads/{job_id}"
ACCESS_KEY = os.getenv("SOCIALKIT_ACCESS_KEY", "").strip()

YT_RE = re.compile(
    r"^(https?://)?(www\.)?(youtube\.com/watch\?v=[\w-]{6,}|youtu\.be/[\w-]{6,}|youtube\.com/shorts/[\w-]{6,})([?&][^\s]*)?$",
    re.I,
)
JOB_RE = re.compile(r"^[A-Za-z0-9_-]{8,100}$")
BITRATES = {"8", "96", "128", "192", "256", "320"}
MAX_SOURCE_BYTES = 2 * 1024 * 1024 * 1024
DOWNLOAD_TIMEOUT = (15, 180)
FFMPEG_TIMEOUT_SECONDS = 600

def valid_youtube_url(url: str) -> bool:
    return bool(YT_RE.match(url.strip()))

def error_page(message, code=502):
    return render_template("download_error.html", message=message), code

def provider_status(job_id):
    if not ACCESS_KEY:
        raise RuntimeError("The conversion provider is not configured. Set SOCIALKIT_ACCESS_KEY in Render.")

    response = requests.get(
        SOCIALKIT_STATUS.format(job_id=job_id),
        headers={"Accept": "application/json", "x-access-key": ACCESS_KEY},
        timeout=(10, 25),
    )

    try:
        body = response.json()
    except ValueError:
        raise RuntimeError("The conversion provider returned an unreadable status response.")

    data = body.get("data") or {}
    if str(data.get("status", "")).lower() == "failed":
        detail = data.get("error") or data.get("message") or body.get("error")
        code = data.get("errorCode")
        suffix = f" (code: {code})" if code else ""
        raise RuntimeError((str(detail) if detail else "The provider could not convert this video.") + suffix)

    if response.status_code >= 400 or not body.get("success"):
        detail = body.get("error") or data.get("message") or data.get("error") or "Could not check conversion status."
        raise RuntimeError(str(detail))

    return data

@app.get("/")
def index():
    return render_template("index.html")

@app.get("/youtube-mp3")
def youtube_mp3():
    return render_template("index.html")

@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "provider_configured": bool(ACCESS_KEY),
        "ffmpeg_available": subprocess.run(
            ["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).returncode == 0,
    })

@app.post("/api/convert")
def convert():
    if not ACCESS_KEY:
        return jsonify({
            "ok": False,
            "error": "The conversion provider is not configured yet. Add SOCIALKIT_ACCESS_KEY in Render."
        }), 503

    body = request.get_json(silent=True) or {}
    url = str(body.get("url", "")).strip()
    bitrate = str(body.get("bitrate", "192")).strip()
    effect = str(body.get("effect", "normal")).strip().lower()

    if not valid_youtube_url(url):
        return jsonify({"ok": False, "error": "Enter a valid YouTube video or Shorts URL."}), 400
    if bitrate not in BITRATES:
        return jsonify({"ok": False, "error": "Choose a supported MP3 bitrate."}), 400
    if effect not in {"normal", "8bit"}:
        return jsonify({"ok": False, "error": "Choose a supported audio effect."}), 400

    # Request WAV from the provider so Jujosmi can choose the MP3 encoding bitrate itself.
    # The provider's `quality` parameter describes video resolution, not MP3 bitrate.
    payload = {
        "access_key": ACCESS_KEY,
        "url": url,
        "format": "wav",
    }

    try:
        response = requests.post(SOCIALKIT_ENDPOINT, json=payload, timeout=(10, 30))
        result = response.json()
    except requests.RequestException:
        return jsonify({"ok": False, "error": "The media provider could not be reached. Please try again."}), 502
    except ValueError:
        return jsonify({"ok": False, "error": "The media provider returned an invalid response."}), 502

    data = result.get("data") or {}
    if response.status_code >= 400 or not result.get("success"):
        message = result.get("error") or data.get("message") or data.get("error") or "The provider could not start conversion."
        return jsonify({"ok": False, "error": str(message)}), 502

    job_id = data.get("jobId")
    if not isinstance(job_id, str) or not JOB_RE.fullmatch(job_id):
        return jsonify({"ok": False, "error": "The provider did not return a valid conversion job ID."}), 502

    return jsonify({
        "ok": True,
        "jobId": job_id,
        "bitrate": bitrate,
        "effect": effect,
        "status": data.get("status", "queued"),
        "title": data.get("title"),
    })

@app.get("/api/status/<job_id>")
def status(job_id):
    if not JOB_RE.fullmatch(job_id):
        return jsonify({"ok": False, "error": "Invalid job ID."}), 400

    try:
        data = provider_status(job_id)
    except requests.RequestException:
        return jsonify({"ok": False, "error": "Could not check conversion status. Please try again."}), 502
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502

    state = str(data.get("status", "unknown")).lower()
    result = {
        "ok": True,
        "status": state,
        "title": data.get("title") or "youtube-audio",
        "progress": data.get("progress"),
    }
    if state == "ready":
        result["downloadPath"] = f"/api/download/{job_id}"
        result["durationSeconds"] = data.get("durationSeconds")
    return jsonify(result)

@app.get("/api/download/<job_id>")
def download(job_id):
    if not JOB_RE.fullmatch(job_id):
        return error_page("That download link is invalid.", 400)

    bitrate = request.args.get("bitrate", "192").strip()
    effect = request.args.get("effect", "normal").strip().lower()
    if bitrate not in BITRATES:
        return error_page("That MP3 quality option is invalid.", 400)
    if effect not in {"normal", "8bit"}:
        return error_page("That audio effect option is invalid.", 400)

    try:
        data = provider_status(job_id)
    except requests.RequestException:
        return error_page("We couldn't check the download with the provider. Please try again.")
    except RuntimeError as exc:
        return error_page(str(exc))

    if str(data.get("status", "")).lower() != "ready":
        return error_page("The source audio is not ready yet. Return to the converter and check the status again.", 409)

    download_url = data.get("downloadUrl")
    if not isinstance(download_url, str):
        return error_page("The provider said the audio was ready but did not return a download link.")

    parsed = urlparse(download_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "amazonaws.com" or host.endswith(".amazonaws.com")):
        return error_page("The provider returned an unexpected download address. No file was downloaded.")

    temp = tempfile.TemporaryDirectory(prefix="jujosmi-mp3-")
    temp_path = Path(temp.name)
    # Let FFmpeg probe the actual container; providers may return a supported audio format different from requested.
    source_path = temp_path / "source.audio"
    output_path = temp_path / "converted.mp3"

    try:
        with requests.get(download_url, stream=True, timeout=DOWNLOAD_TIMEOUT) as upstream:
            if upstream.status_code >= 400:
                return error_page("The temporary audio link was rejected or expired. Please run/check the conversion again and retry.")
            content_type = (upstream.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if content_type.startswith("text/") or "json" in content_type or "xml" in content_type or "html" in content_type:
                return error_page("The provider returned an error message instead of audio. No broken MP3 was saved.")

            try:
                content_length = int(upstream.headers.get("Content-Length", "0"))
            except ValueError:
                content_length = 0
            if content_length > MAX_SOURCE_BYTES:
                return error_page("The source audio is too large for this converter's current 2 GB processing limit.")

            total = 0
            header = bytearray()
            with source_path.open("wb") as out:
                for chunk in upstream.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_SOURCE_BYTES:
                        return error_page("The source audio exceeded this converter's 2 GB processing limit.")
                    if len(header) < 16:
                        header.extend(chunk[:16 - len(header)])
                    out.write(chunk)

        # Reject obvious error documents but allow FFmpeg to detect the actual audio container.
        # The API may return a valid supported audio format with a non-WAV header.
        if len(header) < 4:
            return error_page("The provider returned an empty or incomplete audio source. Please try again.")
        stripped = bytes(header).lstrip().lower()
        if stripped.startswith((b"{", b"[", b"<!doctype", b"<html", b"<?xml")):
            return error_page("The provider returned an error document instead of audio. No broken MP3 was saved.")

        # 8 kbps is the deliberately tiny mono setting. The separate 8-bit effect
        # bit-crushes the signal and narrows bandwidth for a retro/chiptune-like sound.
        output_sample_rate = "8000" if bitrate == "8" else "44100"
        channel_args = ["-ac", "1"] if bitrate == "8" or effect == "8bit" else []
        filter_args = ["-af", "acrusher=bits=8:mode=lin:mix=1"] if effect == "8bit" else []
        if effect == "8bit":
            output_sample_rate = "11025"
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(source_path), "-vn", "-map_metadata", "-1",
                    *filter_args,
                    "-codec:a", "libmp3lame", "-b:a", f"{bitrate}k",
                    "-ar", output_sample_rate, *channel_args, "-id3v2_version", "3",
                    str(output_path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=FFMPEG_TIMEOUT_SECONDS,
                check=False,
            )
        except FileNotFoundError:
            return error_page("FFmpeg is missing from this deployment. Rebuild using the supplied Dockerfile.")
        except subprocess.TimeoutExpired:
            return error_page("Audio encoding took too long. Try a shorter video or a lower bitrate.")

        if result.returncode != 0 or not output_path.exists() or output_path.stat().st_size < 256:
            detail = (result.stderr or "").strip().splitlines()
            human_error = detail[-1][:250] if detail else "The encoder could not create an MP3."
            if "Invalid data found" in (result.stderr or ""):
                return error_page("The provider's download link did not contain a readable audio file. Check the provider job and try again.")
            return error_page(f"MP3 encoding failed: {human_error}")

        safe_title = secure_filename(str(data.get("title") or "youtube-audio"))
        safe_title = os.path.splitext(safe_title)[0] or "youtube-audio"
        effect_suffix = "-8bit-retro" if effect == "8bit" else ""
        filename = f"{safe_title}-{bitrate}kbps{effect_suffix}.mp3"

        response = send_file(
            output_path,
            mimetype="audio/mpeg",
            as_attachment=True,
            download_name=filename,
            conditional=False,
            max_age=0,
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.call_on_close(temp.cleanup)
        return response
    except requests.RequestException:
        temp.cleanup()
        return error_page("The MP3 source could not be downloaded from the provider. Please try again.")
    except Exception:
        temp.cleanup()
        app.logger.exception("MP3 download/encoding failed")
        return error_page("Unexpected error while creating your MP3. Please try again.")
    finally:
        # The response close callback cleans files after streaming. On early returns/errors,
        # TemporaryDirectory also cleans up when the function frame exits.
        pass

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
