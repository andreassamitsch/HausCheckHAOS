# Compile a dedicated localhost-only PO token provider. No host port is opened.
FROM node:22-bookworm-slim AS token-provider-build
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       git ca-certificates python3 make g++ pkg-config libcairo2-dev libpango1.0-dev \
       libjpeg-dev libgif-dev librsvg2-dev \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch 2.0.2 \
       https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil
WORKDIR /opt/bgutil/server
RUN npm ci && npx tsc && npm prune --omit=dev

FROM python:3.12-slim-bookworm
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ffmpeg ca-certificates firefox-esr xvfb x11vnc novnc \
        fonts-dejavu-core dbus-x11 libcairo2 libpangocairo-1.0-0 libjpeg62-turbo libgif7 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --disable-pip-version-check \
       'yt-dlp[default,deno]' 'bgutil-ytdlp-pot-provider==2.0.2' \
       'ytmusicapi>=1.12.4,<2' 'aiohttp>=3.9,<4'
COPY --from=token-provider-build /usr/local/bin/node /usr/local/bin/node
COPY --from=token-provider-build /opt/bgutil/server /opt/bgutil/server

WORKDIR /app
COPY server.py music_catalog.py playback.py auth_ui.py mobile_preview.py run.sh /app/
RUN chmod +x /app/run.sh
EXPOSE 8765 8766
CMD ["/app/run.sh"]
