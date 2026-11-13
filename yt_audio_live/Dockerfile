FROM python:3.12-alpine
RUN apk add --no-cache ffmpeg nodejs ca-certificates \
    && pip install --no-cache-dir --disable-pip-version-check \
       'yt-dlp[default]' 'ytmusicapi>=1.12,<2'
WORKDIR /app
COPY server.py music_catalog.py playback.py /app/
EXPOSE 8765
CMD ["python", "-u", "/app/server.py"]
