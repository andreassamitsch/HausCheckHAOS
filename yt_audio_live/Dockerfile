FROM python:3.12-slim-bookworm

# A genuine local Firefox/X11 browser is used only for Google sign-in.
# VNC stays on loopback; the login UI uses HA Supervisor Ingress.
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ffmpeg nodejs ca-certificates firefox-esr xvfb x11vnc novnc \
        fonts-dejavu-core dbus-x11 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --disable-pip-version-check \
        'yt-dlp[default]' 'ytmusicapi>=1.12.4,<2' 'aiohttp>=3.9,<4'

WORKDIR /app
COPY server.py music_catalog.py playback.py auth_ui.py run.sh /app/
RUN chmod +x /app/run.sh
EXPOSE 8765 8766
CMD ["/app/run.sh"]
