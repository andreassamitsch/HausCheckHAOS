"""Home Assistant OS YouTube Music live streaming and queue API."""
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

import yt_dlp
from music_catalog import Catalog, checked_video_id, checked_playlist_id
from playback import Playback

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("yt_audio_live")
OPTIONS = json.load(open("/data/options.json", encoding="utf-8"))
API_KEY = OPTIONS.get("api_key", "")
BASE_URL = str(OPTIONS.get("stream_base_url", "")).rstrip("/")
PORT = 8765
if not isinstance(API_KEY, str) or len(API_KEY) < 32:
    raise SystemExit("Set a secure api_key (32+ characters) in App options")
if not BASE_URL.startswith("http://"):
    raise SystemExit("stream_base_url must be http://<Home Assistant LAN IPv4>:8765")
parsed_base = urlsplit(BASE_URL)
try:
    if not ipaddress.ip_address(parsed_base.hostname).is_private or parsed_base.port != PORT:
        raise ValueError()
except (ValueError, TypeError):
    raise SystemExit("stream_base_url must use a private LAN IPv4 and port 8765")
CLIENT = str(OPTIONS.get("player_client", "visionos"))
if CLIENT not in ("visionos", "mweb", "web_embedded", "web_safari", "tv"):
    raise SystemExit("Unsupported youtube player_client")

CATALOG = Catalog(OPTIONS.get("ytmusic_auth_json", ""))
SOURCE_CACHE = {}
SOURCE_LOCK = threading.RLock()
STREAM_SLOTS = threading.BoundedSemaphore(3)
VIDEO_RE = re.compile(r"^/stream/([A-Za-z0-9_-]{11})\.mp3$")


def sign_url(vid):
    checked_video_id(vid)
    expiry = int(time.time()) + 3600
    payload = f"{vid}:{expiry}".encode()
    mac = hmac.new(API_KEY.encode(), payload, hashlib.sha256).hexdigest()
    return f"{BASE_URL}/stream/{vid}.mp3?exp={expiry}&sig={mac}"


def validate_stream_url(vid, query):
    try:
        expiry = int((query.get("exp") or ["0"])[0])
        supplied = (query.get("sig") or [""])[0]
    except (ValueError, TypeError):
        return False
    if expiry < time.time() or expiry > time.time() + 3700:
        return False
    expected = hmac.new(API_KEY.encode(), f"{vid}:{expiry}".encode(),
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied)


def resolve_source(vid):
    checked_video_id(vid)
    with SOURCE_LOCK:
        entry = SOURCE_CACHE.get(vid)
        if entry and time.monotonic() - entry["time"] < 85:
            return entry["url"], entry["headers"]
        started = time.monotonic()
        options = {
            "quiet": True, "no_warnings": True, "noplaylist": True,
            "format": "bestaudio/best",
            "skip_download": True, "socket_timeout": 12,
            "retries": 1, "extractor_retries": 1,
            "js_runtimes": {"node": {}},
            "extractor_args": {"youtube": {"player_client": [CLIENT]}},
        }
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(
                "https://www.youtube.com/watch?v=" + vid, download=False)
        url = info.get("url") if isinstance(info, dict) else None
        if not isinstance(url, str) or not url.startswith("https://"):
            raise RuntimeError("No HTTPS audio URL was returned")
        headers = info.get("http_headers", {}) or {}
        SOURCE_CACHE[vid] = {"url": url, "headers": headers,
                             "time": time.monotonic()}
        if len(SOURCE_CACHE) > 15:
            oldest = next(iter(SOURCE_CACHE))
            del SOURCE_CACHE[oldest]
        LOG.info("source_resolved video_id=%s client=%s format=%s elapsed_ms=%d",
                 vid, CLIENT, info.get("format_id"),
                 (time.monotonic()-started)*1000)
        return url, headers


PLAYER = Playback(CATALOG, sign_url, str(OPTIONS.get(
    "player_entity", "media_player.ultra_slim_soundbar")))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "HAYouTubeMusic/0.2"

    def log_message(self, fmt, *args):
        clean = re.sub(r"\?exp=[0-9]+&sig=[a-f0-9]{64}", "?signed", fmt % args)
        LOG.info("client=%s %s", self.client_address[0], clean)

    def json_reply(self, status, value):
        data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def authorized(self):
        header = self.headers.get("X-API-Key", "")
        if not header:
            auth = self.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                header = auth[7:]
        if hmac.compare_digest(header, API_KEY):
            return True
        self.json_reply(401, {"error": "valid API key required"})
        return False

    def get_json(self):
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n < 0 or n > 16384:
                raise ValueError("JSON request must be 16 KB or less")
            value = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(value, dict):
                raise ValueError("JSON object required")
            return value
        except (ValueError, UnicodeError) as exc:
            raise ValueError("Invalid JSON body") from exc

    def do_HEAD(self):
        self.get_route(head=True)

    def do_GET(self):
        self.get_route(head=False)

    def get_route(self, head=False):
        parsed = urlsplit(self.path)
        path = parsed.path
        args = parse_qs(parsed.query)
        if path == "/health":
            return self.json_reply(200, {"ok": True, "version": "0.2.3",
                                         "player_client": CLIENT,
                                         "api_auth": True})
        stream = VIDEO_RE.fullmatch(path)
        if stream:
            vid = stream.group(1)
            if not validate_stream_url(vid, args):
                return self.json_reply(403, {"error": "invalid stream link"})
            if head:
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Connection", "close")
                self.end_headers()
                return
            return self.stream(vid)
        if not path.startswith("/api/"):
            return self.json_reply(404, {"error": "not found"})
        if not self.authorized():
            return
        if head:
            return self.json_reply(405, {"error": "HEAD not supported for API"})
        try:
            if path == "/api/status":
                result = PLAYER.status()
            elif path == "/api/auth":
                result = {"ytmusic_account_connected": CATALOG.authenticated}
            elif path == "/api/search":
                result = {"results": CATALOG.search(
                    (args.get("q") or [""])[0],
                    (args.get("kind") or ["songs"])[0],
                    int((args.get("limit") or ["10"])[0]))}
            elif path == "/api/recommendations":
                vid = checked_video_id((args.get("video_id") or [""])[0])
                result = {"video_id": vid, "tracks": CATALOG.radio(
                    vid, limit=int((args.get("limit") or ["15"])[0]))}
            elif path == "/api/playlist":
                result = CATALOG.playlist(
                    (args.get("id") or [""])[0],
                    int((args.get("limit") or ["100"])[0]))
            elif path == "/api/library":
                result = {"playlists": CATALOG.library_playlists(
                    int((args.get("limit") or ["30"])[0]))}
            elif path == "/api/probe":
                vid = checked_video_id((args.get("video_id") or [""])[0])
                started = time.monotonic()
                url, headers = resolve_source(vid)
                safe_headers = {k: v for k, v in headers.items()
                                if isinstance(v, str) and "\r" not in v and "\n" not in v}
                safe_headers["Range"] = "bytes=0-1023"
                try:
                    with urlopen(Request(url, headers=safe_headers), timeout=15) as response:
                        received = len(response.read(1024))
                        status = response.status
                except HTTPError as exc:
                    status, received = exc.code, 0
                result = {"video_id": vid, "http_status": status,
                          "bytes_received": received,
                          "elapsed_ms": int((time.monotonic()-started)*1000)}
            else:
                return self.json_reply(404, {"error": "unknown API endpoint"})
            return self.json_reply(200, result)
        except (ValueError, TypeError) as exc:
            return self.json_reply(400, {"error": str(exc)[:250]})
        except Exception as exc:
            LOG.error("api_get_failed path=%s error=%s", path, type(exc).__name__)
            return self.json_reply(502, {"error": "catalog or media provider unavailable"})

    def do_POST(self):
        path = urlsplit(self.path).path
        if not path.startswith("/api/"):
            return self.json_reply(404, {"error": "not found"})
        if not self.authorized():
            return
        try:
            body = self.get_json()
            if path == "/api/play":
                if body.get("video_id"):
                    vid = checked_video_id(body["video_id"])
                    track = {"video_id": vid, "title": str(body.get("title") or vid),
                             "artist": body.get("artist") or ""}
                    selected_by_search = False
                else:
                    results = CATALOG.search(body.get("query", ""), limit=5)
                    if not results:
                        raise ValueError("No YouTube Music songs match the query")
                    track, selected_by_search = results[0], True
                # Warm the short-lived audio URL before instructing the Cast receiver.
                resolve_source(track["video_id"])
                result = PLAYER.start(track, radio=bool(body.get("radio", False)))
                result["selected_by_search"] = selected_by_search
            elif path == "/api/queue":
                if isinstance(body.get("tracks"), list):
                    tracks = body["tracks"]
                elif body.get("video_id"):
                    checked_video_id(body["video_id"])
                    tracks = [{"video_id": body["video_id"],
                               "title": body.get("title") or body["video_id"],
                               "artist": body.get("artist") or ""}]
                else:
                    matches = CATALOG.search(body.get("query", ""), limit=5)
                    if not matches:
                        raise ValueError("No matching song found")
                    tracks = [matches[0]]
                result = PLAYER.enqueue(tracks)
            elif path == "/api/playlist":
                playlist_id = checked_playlist_id(body.get("playlist_id"))
                playlist = CATALOG.playlist(playlist_id,
                                            limit=int(body.get("limit", 100)))
                tracks = playlist["tracks"]
                if not tracks:
                    raise ValueError("Playlist contains no playable songs")
                if body.get("shuffle"):
                    import random
                    random.SystemRandom().shuffle(tracks)
                resolve_source(tracks[0]["video_id"])
                result = PLAYER.start(tracks[0], rest=tracks[1:],
                                      radio=bool(body.get("radio_after", False)))
                result["playlist_title"] = playlist["title"]
            elif path == "/api/radio":
                enabled = bool(body.get("enabled", True))
                seed = body.get("video_id")
                if body.get("start_now") and seed:
                    vid = checked_video_id(seed)
                    resolve_source(vid)
                    result = PLAYER.start({"video_id": vid, "title": vid}, radio=enabled)
                else:
                    result = PLAYER.set_radio(enabled, seed=seed)
            elif path in ("/api/next", "/api/skip"):
                result = PLAYER.next()
            elif path == "/api/stop":
                result = PLAYER.stop()
            elif path == "/api/pause":
                result = PLAYER.pause()
            elif path == "/api/resume":
                result = PLAYER.resume()
            else:
                return self.json_reply(404, {"error": "unknown API endpoint"})
            return self.json_reply(200, result)
        except (ValueError, TypeError) as exc:
            return self.json_reply(400, {"error": str(exc)[:250]})
        except Exception as exc:
            LOG.error("api_post_failed path=%s error=%s", path, type(exc).__name__)
            return self.json_reply(502, {"error": "playback request failed"})

    def stream(self, vid):
        if not STREAM_SLOTS.acquire(blocking=False):
            return self.json_reply(429, {"error": "too many simultaneous streams"})
        started = time.monotonic()
        proc = None
        try:
            source, source_headers = resolve_source(vid)
            command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin"]
            for header, switch in (("User-Agent", "-user_agent"),
                                   ("Referer", "-referer")):
                value = source_headers.get(header)
                if isinstance(value, str) and value and "\r" not in value and "\n" not in value:
                    command.extend((switch, value))
            command.extend([
                "-rw_timeout", "15000000", "-i", source, "-vn", "-map", "0:a:0",
                "-c:a", "libmp3lame", "-b:a", "128k", "-f", "mp3",
                "-flush_packets", "1", "pipe:1"])
            proc = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    bufsize=0)
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            count = 0
            while True:
                piece = proc.stdout.read(8192)
                if not piece:
                    break
                if not count:
                    LOG.info("first_audio_bytes video_id=%s latency_ms=%d",
                             vid, (time.monotonic()-started)*1000)
                self.wfile.write(("%X\r\n" % len(piece)).encode())
                self.wfile.write(piece)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
                count += len(piece)
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            LOG.info("client_closed_stream video_id=%s", vid)
        except Exception as exc:
            LOG.error("stream_error video_id=%s error=%s", vid, type(exc).__name__)
        finally:
            if proc:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                proc.stdout.close()
                stderr = proc.stderr.read(1600).decode("utf-8", "replace")
                proc.stderr.close()
                if stderr and proc.returncode:
                    LOG.warning("ffmpeg_failed video_id=%s code=%s error=%r",
                                vid, proc.returncode,
                                re.sub(r"https?://\S+", "[redacted-url]", stderr)[:400])
                LOG.info("stream_done video_id=%s exit_code=%s elapsed_ms=%d",
                         vid, proc.returncode, (time.monotonic()-started)*1000)
            STREAM_SLOTS.release()


if __name__ == "__main__":
    LOG.info("server_started version=0.2.3 player_client=%s player=%s",
             CLIENT, PLAYER.entity_id)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever(poll_interval=0.25)
