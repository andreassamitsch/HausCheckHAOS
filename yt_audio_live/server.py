"""Local single-video YouTube live audio proxy for Home Assistant OS."""
import json
import logging
import os
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import yt_dlp

LOG = logging.getLogger("yt_audio_live")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
VIDEO_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
PORT = 8765
APP_OPTIONS = json.load(open("/data/options.json", encoding="utf-8"))
VIDEO_ID = APP_OPTIONS.get("video_id", "")
CLIENT = APP_OPTIONS.get("player_client", "web_embedded")
if CLIENT not in ("web_embedded", "tv", "web_safari", "mweb", "android_vr"):
    raise SystemExit("Unsupported player_client")
if not isinstance(VIDEO_ID, str) or not VIDEO_RE.fullmatch(VIDEO_ID):
    raise SystemExit("Invalid video_id; expected an 11-character YouTube video ID")

SOURCE_CACHE = {"url": None, "headers": {}, "time": 0.0}
SOURCE_LOCK = threading.Lock()
STREAM_LOCK = threading.BoundedSemaphore(1)


def resolve_source():
    with SOURCE_LOCK:
        if SOURCE_CACHE["url"] and time.monotonic() - SOURCE_CACHE["time"] < 90:
            return SOURCE_CACHE["url"], SOURCE_CACHE["headers"]
        t0 = time.monotonic()
        options = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "format": "bestaudio/best",
            "extractor_args": {"youtube": {"player_client": [CLIENT]}},
            "skip_download": True,
            "socket_timeout": 12,
            "retries": 1,
            "extractor_retries": 1,
            "js_runtimes": {"node": {}},
        }
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(
                "https://www.youtube.com/watch?v=" + VIDEO_ID, download=False
            )
        url = info.get("url") if isinstance(info, dict) else None
        if not url or not url.startswith("https://"):
            raise RuntimeError("No HTTPS media URL returned by yt-dlp")
        headers = info.get("http_headers", {}) or {}
        SOURCE_CACHE.update(url=url, headers=headers, time=time.monotonic())
        LOG.info("resolved_format client=%s id=%s ext=%s protocol=%s",
                 CLIENT,
                 info.get("format_id"), info.get("ext"), info.get("protocol"))
        LOG.info("source_resolved id=%s latency_ms=%d title=%r",
                 VIDEO_ID, (time.monotonic() - t0) * 1000, info.get("title"))
        return url, headers


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "HAYouTubeAudio/0.1"

    def log_message(self, fmt, *args):
        LOG.info("client=%s " + fmt, self.client_address[0], *args)

    def send_common(self, content_type):
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("Connection", "close")

    def respond_json(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_common("application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def do_HEAD(self):
        self.handle_request(head=True)

    def do_GET(self):
        self.handle_request(head=False)

    def handle_request(self, head):
        path = urlsplit(self.path).path
        if path == "/probe":
            return self.probe_source()
        if path == "/health":
            return self.respond_json(200, {
                "ok": True, "video_id": VIDEO_ID, "mode": "live-mp3",
            })
        if path != "/stream/" + VIDEO_ID + ".mp3":
            return self.respond_json(404, {"error": "not found"})
        if head:
            self.send_response(200)
            self.send_common("audio/mpeg")
            self.end_headers()
            return
        if not STREAM_LOCK.acquire(blocking=False):
            return self.respond_json(429, {"error": "stream already active"})
        try:
            self.stream_audio()
        finally:
            STREAM_LOCK.release()

    def probe_source(self):
        t0 = time.monotonic()
        try:
            url, headers = resolve_source()
            probe_headers = {k: v for k, v in headers.items()
                             if isinstance(v, str) and "\r" not in v and "\n" not in v}
            probe_headers["Range"] = "bytes=0-1023"
            with urlopen(Request(url, headers=probe_headers), timeout=15) as response:
                data = response.read(1024)
                status = response.status
                mime = response.headers.get("Content-Type", "")
            return self.respond_json(200, {"client": CLIENT, "http_status": status,
                        "content_type": mime, "bytes_received": len(data),
                        "elapsed_ms": int((time.monotonic()-t0)*1000)})
        except HTTPError as exc:
            LOG.warning("source_probe_failed client=%s code=%s", CLIENT, exc.code)
            return self.respond_json(200, {"client": CLIENT, "http_status": exc.code,
                        "elapsed_ms": int((time.monotonic()-t0)*1000)})
        except Exception as exc:
            LOG.warning("source_probe_error client=%s error=%s", CLIENT, type(exc).__name__)
            return self.respond_json(502, {"client": CLIENT, "error": type(exc).__name__})

    def stream_audio(self):
        started = time.monotonic()
        try:
            source, source_headers = resolve_source()
        except Exception as exc:
            LOG.error("extract_failed id=%s error=%s", VIDEO_ID, exc)
            return self.respond_json(502, {"error": "source extraction failed"})

        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin"]
        for header_name, ffmpeg_arg in (
            ("User-Agent", "-user_agent"), ("Referer", "-referer")
        ):
            value = source_headers.get(header_name, "")
            if isinstance(value, str) and value and "\r" not in value and "\n" not in value:
                command.extend((ffmpeg_arg, value))
        command.extend([
            "-rw_timeout", "15000000", "-i", source,
            "-vn", "-map", "0:a:0",
            "-c:a", "libmp3lame", "-b:a", "128k",
            "-f", "mp3", "-flush_packets", "1", "pipe:1"
        ])
        try:
            proc = subprocess.Popen(
                command, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
            )
        except OSError as exc:
            LOG.error("ffmpeg_failed %s", exc)
            return self.respond_json(502, {"error": "ffmpeg could not start"})

        total = 0
        try:
            self.send_response(200)
            self.send_common("audio/mpeg")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            while True:
                data = proc.stdout.read(4096)
                if not data:
                    break
                if not total:
                    LOG.info("first_audio_bytes latency_ms=%d",
                             (time.monotonic() - started) * 1000)
                self.wfile.write(("%X\r\n" % len(data)).encode("ascii"))
                self.wfile.write(data)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
                total += len(data)
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            LOG.info("client_disconnected bytes_sent=%d", total)
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            proc.stdout.close()
            if proc.stderr:
                err = proc.stderr.read(2000).decode("utf-8", "replace")
                proc.stderr.close()
                if err and proc.returncode:
                    clean = re.sub(r"https?://\S+", "[redacted-url]", err)
                    LOG.warning("ffmpeg_diagnostic code=%s message=%r",
                                proc.returncode, clean[:700])
            LOG.info("stream_ended bytes=%d duration_ms=%d exit_code=%s",
                     total, (time.monotonic() - started) * 1000, proc.returncode)


if __name__ == "__main__":
    LOG.info("starting fixed_video_id=%s client=%s port=%d", VIDEO_ID, CLIENT, PORT)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever(poll_interval=0.25)
