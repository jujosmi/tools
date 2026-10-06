# Jujosmi YouTube → MP3 Web App

A real web page and server-side converter. Visitors open the site in a browser, paste a YouTube URL, and receive an MP3 download.

## What this contains

- Responsive Jujosmi-styled web page
- `/youtube-mp3` route for hosting at `tools.jujosmi.com/youtube-mp3`
- `POST /api/convert` conversion endpoint
- FFmpeg MP3 extraction via yt-dlp
- Health check at `/health`
- Docker deployment configuration
- Render blueprint (`render.yaml`)

## Run locally

Requirements:
- Python 3.11+
- FFmpeg installed and available on PATH
- Deno installed and available on PATH

```bash
python -m venv .venv
.venv\\Scripts\\activate   # Windows
pip install -r requirements.txt
python app.py
```

Open `http://localhost:8080/youtube-mp3`.

## Put it on the internet

The simplest route is Render:

1. Create a GitHub repository and upload this folder.
2. In Render, create a new **Blueprint** from the repository.
3. Render reads `render.yaml` and starts the Docker web service.
4. Test the generated Render URL at `/youtube-mp3`.
5. Add your custom domain, e.g. `tools.jujosmi.com`.
6. Point your DNS record for `tools.jujosmi.com` to the Render-provided target.

For `tools.jujosmi.com/youtube-mp3`, the Flask app already serves the page at that path.

## Important production note

Public conversion can be resource-intensive. Add rate limits, request logging, abuse protection, and a queue before opening it to a large audience. Use it only for media you have the right to download.
