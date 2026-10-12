# Jujosmi YouTube → MP3 — Quality Selector

Adds user-selectable MP3 encoding at 96, 128, 192, 256, or 320 kbps.

## How quality works
The SocialKit API exposes an audio format but does not document an MP3 bitrate parameter. This build asks SocialKit for WAV audio, then uses FFmpeg on the Jujosmi server to encode the MP3 at the selected bitrate. The selected bitrate affects the MP3 encoding and file size; it cannot recover detail absent from the original source.

## Deployment
Replace the repository files with this project, preserving `templates/` and `static/`, then commit and deploy the latest commit on Render. Keep `SOCIALKIT_ACCESS_KEY` configured as a Render environment variable.

## Requirements
The supplied Dockerfile installs FFmpeg. Do not deploy using an old Docker image; create a new build from the latest commit.

## Quality options
- Potato quality — 8 kbps (8 kHz sample rate; intentionally very poor fidelity)
- Low — 96 kbps
- Standard — 128 kbps
- High — 192 kbps
- Very High — 256 kbps
- Extremely High — 320 kbps

Only use it for content you own or are authorized to download/convert.
