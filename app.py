import os
import re
import time
import requests
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

SOCIALKIT_ENDPOINT = "https://api.socialkit.dev/v2/youtube/download"
SOCIALKIT_STATUS = "https://api.socialkit.dev/v2/downloads/{job_id}"
ACCESS_KEY = os.getenv("SOCIALKIT_ACCESS_KEY", "").strip()

YT_RE = re.compile(
    r"^(https?://)?(www\.)?(youtube\.com/watch\?v=[\w-]{6,}|youtu\.be/[\w-]{6,}|youtube\.com/shorts/[\w-]{6,})([?&][^\s]*)?$",
    re.I,
)

def valid_youtube_url(url: str) -> bool:
    return bool(YT_RE.match(url.strip()))

def api_headers():
    return {"Content-Type": "application/json", "Accept": "application/json"}

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

    data = request.get_json(silent=True) or {}
    url = str(data.get("url", "")).strip()

    if not valid_youtube_url(url):
        return jsonify({"ok": False, "error": "Enter a valid YouTube video or Shorts URL."}), 400

    payload = {
        "access_key": ACCESS_KEY,
        "url": url,
        "format": "mp3",
        "quality": "480p",
    }

    try:
        r = requests.post(SOCIALKIT_ENDPOINT, json=payload, headers=api_headers(), timeout=30)
        result = r.json()
    except requests.RequestException:
        return jsonify({"ok": False, "error": "The media provider could not be reached."}), 502
    except ValueError:
        return jsonify({"ok": False, "error": "The media provider returned an invalid response."}), 502

    if r.status_code >= 400 or not result.get("success"):
        message = (
            result.get("error")
            or (result.get("data") or {}).get("message")
            or "The provider could not start the conversion."
        )
        return jsonify({"ok": False, "error": str(message)}), 502

    data_obj = result.get("data") or {}
    job_id = data_obj.get("jobId")
    if not job_id:
        return jsonify({"ok": False, "error": "The provider did not return a conversion job."}), 502

    return jsonify({
        "ok": True,
        "jobId": job_id,
        "status": data_obj.get("status", "queued"),
        "title": data_obj.get("title"),
    })

@app.get("/api/status/<job_id>")
def status(job_id):
    if not ACCESS_KEY:
        return jsonify({"ok": False, "error": "Provider is not configured."}), 503

    if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", job_id):
        return jsonify({"ok": False, "error": "Invalid job id."}), 400

    try:
        r = requests.get(
            SOCIALKIT_STATUS.format(job_id=job_id),
            headers={"Accept": "application/json", "x-access-key": ACCESS_KEY},
            timeout=20,
        )
        result = r.json()
    except requests.RequestException:
        return jsonify({"ok": False, "error": "Could not check conversion status."}), 502
    except ValueError:
        return jsonify({"ok": False, "error": "Invalid status response from provider."}), 502

    if r.status_code >= 400 or not result.get("success"):
        data_obj = result.get("data") or {}
        message = result.get("error") or data_obj.get("message") or "Conversion status unavailable."
        return jsonify({"ok": False, "error": str(message)}), 502

    data_obj = result.get("data") or {}
    status_value = str(data_obj.get("status", "unknown")).lower()

    if status_value == "ready":
        download_url = data_obj.get("downloadUrl")
        if not download_url:
            return jsonify({"ok": False, "error": "Conversion finished without a download link."}), 502
        return jsonify({
            "ok": True,
            "status": "ready",
            "title": data_obj.get("title") or "youtube-audio",
            "downloadUrl": download_url,
            "filename": (data_obj.get("title") or "youtube-audio") + ".mp3",
            "durationSeconds": data_obj.get("durationSeconds"),
            "fileSizeMB": data_obj.get("fileSizeMB"),
        })

    if status_value == "failed":
        return jsonify({
            "ok": False,
            "status": "failed",
            "error": data_obj.get("error") or data_obj.get("message") or "The provider could not convert this video."
        }), 502

    return jsonify({
        "ok": True,
        "status": status_value,
        "progress": data_obj.get("progress"),
        "title": data_obj.get("title"),
    })

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
