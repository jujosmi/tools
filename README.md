# Jujosmi YouTube → MP3 (Render)

This version uses a hosted YouTube media-conversion API instead of having your Render container scrape YouTube directly.

## Important
Only use the tool for content you own or have permission to download/convert.

## Setup

1. Create a SocialKit account and obtain an API access key.
2. Push this project to GitHub.
3. Deploy it as a Render Web Service using the included Dockerfile.
4. In Render, add an environment variable:
   - `SOCIALKIT_ACCESS_KEY` = your SocialKit access key
5. Deploy.

## Routes

- `/` — homepage
- `/youtube-mp3` — same converter page
- `/health` — health check

## How it works

Browser
→ Jujosmi Flask app
→ SocialKit YouTube async download API
→ temporary MP3 URL
→ browser download

The provider supports MP3 output and returns a temporary download URL. The async API is intended for longer videos and reports `queued`, `processing`, `ready`, or `failed` states.

## Notes

- The API key is read only from the server environment; it is not exposed in the frontend.
- No YouTube cookies are required.
- No Deno or yt-dlp is required in this build.
- The provider's free plan can be used for initial testing, with limited credits.
