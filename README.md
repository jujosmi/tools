# Jujosmi YouTube → MP3

A Flask web app for converting a YouTube video URL into a 192 kbps MP3 using yt-dlp and FFmpeg.

## Render deployment

This repo is designed for a Render Docker Web Service.

The Docker image installs:
- FFmpeg
- Deno (yt-dlp's recommended JS runtime)
- yt-dlp with its default EJS dependency group
- BgUtils PO-token provider 2.0.1 and its local provider server

The container starts the BgUtils provider privately on `127.0.0.1:4416` and Gunicorn on Render's `$PORT`.

## Repository layout

```text
app.py
Dockerfile
Procfile
render.yaml
requirements.txt
start.sh
templates/index.html
static/app.js
static/styles.css
```

## Important

YouTube can still apply IP-based anti-bot/login checks to datacenter IPs. The PO-token provider helps with current token requirements but does not guarantee bypassing every YouTube bot check.

An optional `YOUTUBE_COOKIES_B64` environment variable is supported for legitimate authenticated use. Treat exported cookies as credentials: never commit them to GitHub.

Use the service only for content you are authorized to download.
