FROM python:3.12-alpine
RUN apk add --no-cache ffmpeg nodejs ca-certificates \
    && pip install --no-cache-dir --disable-pip-version-check 'yt-dlp[default]'
WORKDIR /app
COPY server.py /app/server.py
EXPOSE 8765
CMD ["python", "-u", "/app/server.py"]
