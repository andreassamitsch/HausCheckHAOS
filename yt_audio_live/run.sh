#!/bin/sh
set -eu

# Music API keeps running even if Google sign-in browser exits.
export DISPLAY=:99
export HOME=/data
mkdir -p /data/ytmusic_auth_browser
chmod 700 /data/ytmusic_auth_browser

Xvfb :99 -screen 0 680x900x24 -nolisten tcp -ac >/dev/null 2>&1 &
sleep 1

# Firefox runs as a genuine local browser; login credentials remain in Google.
# Password manager disabled; only session cookies should be retained.
cat > /data/ytmusic_auth_browser/user.js <<'PREFS'
user_pref("signon.rememberSignons", false);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.startup.homepage", "https://music.youtube.com");
user_pref("browser.newtabpage.enabled", false);
user_pref("browser.aboutConfig.showWarning", false);
user_pref("layout.css.devPixelsPerPx", "1.30");
PREFS
firefox-esr --no-remote --kiosk --profile /data/ytmusic_auth_browser "https://music.youtube.com" \
  >/dev/null 2>&1 &

# VNC binds to loopback only. It is reachable outside the container
# solely through the authenticated HA Ingress websocket bridge.
x11vnc -display :99 -rfbport 5900 -localhost -forever -shared -nopw -quiet \
  >/dev/null 2>&1 &

# Automatic video-bound proof-of-origin tokens; private to this container.
# Never publish port 4416. The provider is required only for YouTube extraction.
(
  cd /opt/bgutil/server
  exec /usr/local/bin/node build/main.js --host 127.0.0.1 --port 4416
) >/dev/null 2>&1 &

python -u /app/auth_ui.py &
exec python -u /app/server.py
