# Jujosmi YouTube → MP3 — Download Fix

This build proxies the download through the Flask backend, checks the provider response before returning it as an MP3, and shows an error page instead of saving tiny JSON/XML error bodies as `.mp3`.

## Keep your existing Render secret
`SOCIALKIT_ACCESS_KEY` must remain set in Render. Do not commit it to GitHub.

## If replacing just files in GitHub
Replace:
- `app.py`
- `static/app.js`

Add:
- `templates/download_error.html`

You do not need to change the Dockerfile, Procfile, `requirements.txt`, or your existing styles for this fix.

Then commit and deploy latest commit in Render.

## What changed
- Browser downloads from `/api/download/<job_id>` on this app, not directly from the temporary provider URL.
- The server obtains a fresh URL by checking the async job when the user clicks Download.
- It validates the provider-issued HTTPS Amazon S3 host.
- It rejects small/text/JSON/XML responses before setting MP3 download headers.
- Failed or expired URLs now show a readable error page rather than downloading a 78-byte unusable file.

Use only for content you own or are authorized to download/convert.
