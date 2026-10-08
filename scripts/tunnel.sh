#!/usr/bin/env bash
# Put the running app (make app) on the internet through a Cloudflare quick tunnel: a random https://*.trycloudflare.com
# address, no Cloudflare account needed. Caddy (runtime/bin/caddy) joins the two servers behind one local address, and the
# settings for public use go to runtime/tunnel.env, which `make app` reads after .env. Stop with: make tunnel-stop
set -euo pipefail
cd "$(dirname "$0")/.."
DIR=runtime/tunnel
if [ "${1:-}" = "stop" ]; then
	for f in "$DIR"/caddy.pid "$DIR"/cloudflared.pid; do [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null; rm -f "$f"; done
	rm -f runtime/tunnel.env "$DIR/url"
	echo "Tunnel stopped; restart the app (make app) to go back to local addresses."
	exit 0
fi
CADDY=${CADDY:-runtime/bin/caddy}
mkdir -p "$DIR"
command -v cloudflared >/dev/null || { echo "cloudflared is not installed"; exit 1; }
[ -x "$CADDY" ] || { echo "Caddy not found at $CADDY (see docs: make tunnel)"; exit 1; }
"$0" stop >/dev/null 2>&1 || true

setsid nohup "$CADDY" run --config deploy/Caddyfile.tunnel --adapter caddyfile >"$DIR/caddy.log" 2>&1 &
echo $! >"$DIR/caddy.pid"
setsid nohup cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8080 >"$DIR/cloudflared.log" 2>&1 &
echo $! >"$DIR/cloudflared.pid"

URL=""
for _ in $(seq 1 90); do
	URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$DIR/cloudflared.log" | head -1 || true)
	[ -n "$URL" ] && break
	sleep 1
done
[ -n "$URL" ] || { echo "No tunnel address after 90 s; see $DIR/cloudflared.log"; exit 1; }

cat >runtime/tunnel.env <<ENV
# Written by scripts/tunnel.sh for the public tunnel; removed by make tunnel-stop.
FLOODCAT_APP_URL=$URL
FLOODCAT_AUTH_URL=$URL
FLOODCAT_CORS_ORIGINS=$URL
FLOODCAT_COOKIE_SECURE=1
# Public: sign-in throttles on, and the Gemini key kept away from strangers (AI runs on the local Ollama model).
FLOODCAT_AUTH_THROTTLE=1
GEMINI_API_KEY=
GOOGLE_API_KEY=
ENV
echo "$URL" >"$DIR/url"
echo "Public address: $URL"
echo "Restart the app so it uses this address: stop it, then run make app."
