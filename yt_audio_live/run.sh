#!/bin/sh
set -eu

# Music, catalog and authenticated Ingress remain online.
# Firefox, Xvfb and VNC are now launched only by an explicit Login button.
# The LoginBrowser manager shuts them down after session capture or idle time.
export HOME=/data
mkdir -p /data/ytmusic_auth_browser
chmod 700 /data/ytmusic_auth_browser

# Automatic video-bound proof-of-origin tokens; private to this container.
# Never publish port 4416. The provider is required only for YouTube extraction.
(
  cd /opt/bgutil/server
  exec /usr/local/bin/node build/main.js --host 127.0.0.1 --port 4416
) >/dev/null 2>&1 &

python -u /app/auth_ui.py &
exec python -u /app/server.py
