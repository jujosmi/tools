#!/bin/sh
set -eu

# Start the BgUtils PO-token server on the loopback interface. It is not exposed publicly.
(
  cd /opt/bgutil-ytdlp-pot-provider/server/node_modules
  exec deno run \
    --allow-env \
    --allow-net \
    --allow-ffi=. \
    --allow-read=. \
    ../src/main.ts \
    --host 127.0.0.1 \
    --port 4416
) &
POT_PID=$!

cleanup() {
  kill "$POT_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Give the provider a few seconds to initialize before the web app accepts traffic.
i=0
while [ "$i" -lt 30 ]; do
  if curl -s --max-time 1 http://127.0.0.1:4416/ >/dev/null 2>&1; then
    break
  fi
  i=$((i + 1))
  sleep 1
done

exec gunicorn \
  --bind "0.0.0.0:${PORT:-8080}" \
  --workers 1 \
  --threads 4 \
  --timeout 300 \
  app:app
