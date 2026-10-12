import os
import re
from urllib.parse import urlparse

import requests
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from werkzeug.utils import secure_filename
from markupsafe import escape

app = Flask(__name__)

SOCIALKIT_ENDPOINT = "https://api.socialkit.dev/v2/youtube/download"
SOCIALKIT_STATUS = "https://api.socialkit.dev/v2/downloads/{job_id}"
ACCESS_KEY = os.getenv("SOCIALKIT_ACCESS_KEY", "").strip()
REQUEST_TIMEOUT = (10, 180)

YT_RE = re.compile(
    r"^(https?://)?(www\.)?(youtube\.com/watch\?v=[\w-]{6,}|youtu\.be/[\w-]{6,}|youtube\.com/shorts/[\w-]{6,})([?&][^\s]*)?$",
    re.I,
)
JOB_RE = re.compile(r"^[A-Za-z0-9_-]{8,100}$")

def valid_youtube_url(url: str) -> bool:
    return bool(YT_RE.match(url.strip()))

def error_page(message, code=502):
    return render_template("download_error.html", message=message), code

def provider_status(job_id):
    """Return provider job data or raise a readable RuntimeError."""
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
    # The provider may return HTTP 200 even when a job status is failed.
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
    return jsonify({"ok": True, "provider_configured": bool(ACCESS_KEY)})

@app.post("/api/convert")
def convert():
    if not ACCESS_KEY:
        return jsonify({
            "ok": False,
            "error": "The conversion provider is not configured yet. Add SOCIALKIT_ACCESS_KEY in Render."
        }), 503

    body = request.get_json(silent=True) or {}
    url = str(body.get("url", "")).strip()

    if not valid_youtube_url(url):
        return jsonify({"ok": False, "error": "Enter a valid YouTube video or Shorts URL."}), 400

    payload = {
        "access_key": ACCESS_KEY,
        "url": url,
        "format": "mp3",
        "quality": "480p",
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
        # Do not send the third-party URL to the browser; route downloads through our backend
        # so we can detect error responses and avoid saving tiny JSON/XML files as MP3s.
        result["downloadPath"] = f"/api/download/{job_id}"
        result["fileSizeMB"] = data.get("fileSizeMB")
        result["durationSeconds"] = data.get("durationSeconds")
    return jsonify(result)

@app.get("/api/download/<job_id>")
def download(job_id):
    if not JOB_RE.fullmatch(job_id):
        return error_page("That download link is invalid.", 400)

    try:
        data = provider_status(job_id)
    except requests.RequestException:
        return error_page("We couldn't check the download with the provider. Please try again.")
    except RuntimeError as exc:
        return error_page(str(exc))

    if str(data.get("status", "")).lower() != "ready":
        return error_page("The MP3 is not ready yet. Return to the converter and check the status again.", 409)

    download_url = data.get("downloadUrl")
    if not isinstance(download_url, str):
        return error_page("The provider said the job was ready but did not return a download link.")

    parsed = urlparse(download_url)
    # Only follow provider-issued HTTPS Amazon S3 download URLs. This also prevents user-controlled
    # URLs from being used to make requests from the server.
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (
        host == "amazonaws.com" or host.endswith(".amazonaws.com")
    ):
        return error_page("The provider returned an unexpected download address. No file was downloaded.")

    try:
        upstream = requests.get(download_url, stream=True, timeout=REQUEST_TIMEOUT)
    except requests.RequestException:
        return error_page("The MP3 host could not be reached. Please retry the download.")

    if upstream.status_code >= 400:
        upstream.close()
        return error_page("The temporary MP3 link was rejected or expired. Go back, run/check the conversion again, and retry.")

    content_type = (upstream.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    content_length = upstream.headers.get("Content-Length")
    try:
        too_small = content_length is not None and int(content_length) < 256
    except ValueError:
        too_small = False

    # Read the first chunk before sending download headers. Error pages/JSON from a failed URL
    # must not be delivered to the visitor with a .mp3 filename.
    iterator = upstream.iter_content(chunk_size=64 * 1024)
    first_chunk = next(iterator, b"")

    textual = (
        content_type.startswith("text/")
        or "json" in content_type
        or "xml" in content_type
        or first_chunk.lstrip().startswith((b"{", b"[", b"<!DOCTYPE", b"<html", b"<?xml"))
    )
    if not first_chunk or too_small or textual:
        upstream.close()
        return error_page("The provider's link returned an error response instead of MP3 audio. The bad response was blocked instead of being saved as a file.")

    title = str(data.get("title") or "youtube-audio")
    filename = secure_filename(title) or "youtube-audio"
    if not filename.lower().endswith(".mp3"):
        filename += ".mp3"

    def stream_file():
        try:
            yield first_chunk
            for chunk in iterator:
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    headers = {
        "Content-Type": "audio/mpeg",
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if content_length and not too_small:
        headers["Content-Length"] = content_length

    return Response(stream_with_context(stream_file()), headers=headers, direct_passthrough=True)

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
