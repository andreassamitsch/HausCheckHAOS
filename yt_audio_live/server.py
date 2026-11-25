"""Home Assistant OS YouTube Music live streaming and queue API."""
import hashlib
import importlib.metadata
import hmac
import ipaddress
import json
import logging
import os
import re
import subprocess
import threading
import tempfile
import shutil
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen
from pathlib import Path

import yt_dlp
from music_catalog import Catalog, checked_video_id, checked_playlist_id
from playback import Playback
from audio_level import AudioLevel, measure, input_args

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
CLIENT = str(OPTIONS.get("player_client", "web_music"))
if CLIENT not in ("web_music", "auto", "mweb", "web_embedded", "web_safari",
                  "tv", "visionos"):
    raise SystemExit("Unsupported youtube player_client")

SESSION_FILE = Path("/data/ytmusic-session-cookies.txt")


def load_catalog():
    """Read login session from the App's private persistent data first."""
    if SESSION_FILE.is_file():
        try:
            return Catalog(SESSION_FILE.read_text(encoding="utf-8"))
        except (ValueError, OSError, TypeError):
            LOG.warning("stored_session_invalid")
    return Catalog(OPTIONS.get("ytmusic_auth_json", ""))


CATALOG = load_catalog()
SOURCE_CACHE = {}
SOURCE_LOCK = threading.RLock()
SOURCE_EPOCH = 0
SOURCE_TTL = 240
WARM_LOCK = threading.Lock()
WARM_PENDING = []
WARM_RUNNING = False
WARM_LAST = {}
WARM_INFLIGHT = {}
STREAM_SLOTS = threading.BoundedSemaphore(3)
LEVEL_PROBE_SLOT = threading.BoundedSemaphore(1)
AUDIO_LEVEL = AudioLevel()

class AudioSourceUnavailable(RuntimeError):
    """YouTube audio source could not be resolved."""


def diagnostic_reason(message):
    """Return only fixed labels and HTTP codes; never output upstream text."""
    value = str(message).lower()
    reasons = []
    checks = (
        ("login_required", ("sign in", "log in", "login required", "login_required")),
        ("bot_challenge", ("not a bot", "confirm you're not", "confirm you’re not", "captcha")),
        ("cookies_expired_or_invalid", ("cookies are no longer valid", "cookies have expired", "cookie has expired", "invalid cookies", "cookie rotation", "cookies are likely")),
        ("client_rejected", ("not supported on this client", "client is not supported", "client does not support", "does not support cookies", "not available on this app")),
        ("no_formats", ("requested format is not available", "no video formats", "no formats", "only images are available")),
        ("content_unavailable", ("video unavailable", "video is unavailable", "private video", "members-only", "not available in your country", "age-restricted")),
        ("pot_missing", ("no po token", "po token was not provided", "missing po token", "requires a po token", "required po token")),
        ("pot_generation_failed", ("failed to generate", "unable to generate", "could not generate", "error generating", "no po token provider", "pot provider failed")),
        ("js_challenge_failed", ("signature extraction failed", "nsig extraction failed", "n challenge", "signature challenge", "javascript challenge", "no supported javascript runtime", "challenge solving failed")),
        ("network_timeout", ("timed out", "timeout")),
        ("connection_refused", ("connection refused", "econnrefused")),
        ("tls_error", ("certificate verify failed", "ssl error", "tls error")),
        ("dns_error", ("name resolution", "getaddrinfo", "enotfound")),
        ("rate_limited", ("too many requests", "rate limit")),
        ("provider_unreachable", ("unable to connect", "failed to connect", "connection reset", "econnreset")),
        ("provider_dependency", ("cannot find module", "module not found", "err_module_not_found", "not defined", "not a function")),
    )
    for label, patterns in checks:
        if any(pattern in value for pattern in patterns):
            reasons.append(label)
    for code in re.findall(r"\b(?:http(?: error| status)?[ :]+|status(?: code)?[ :=]+)([45][0-9]{2})\b", value):
        if "http_" + code not in reasons:
            reasons.append("http_" + code)
    if not reasons and ("po token" in value or "po_token" in value):
        reasons.append("pot_related")
    return ",".join(reasons) or "unclassified"


def log_runtime_versions():
    versions = {}
    for package in ("yt-dlp", "yt-dlp-ejs", "bgutil-ytdlp-pot-provider", "ytmusicapi"):
        try:
            v = importlib.metadata.version(package)
            versions[package] = v if re.fullmatch(r"[A-Za-z0-9.+_-]{1,60}", v) else "unknown"
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not_installed"
    for runtime in ("deno", "node"):
        try:
            out = subprocess.run([runtime, "--version"], capture_output=True,
                                 text=True, timeout=5, check=True).stdout.splitlines()
            match = re.search(r"\b(?:v)?([0-9]+\.[0-9]+\.[0-9]+)\b", out[0] if out else "")
            versions[runtime] = match.group(1) if match else "unknown"
        except (OSError, subprocess.SubprocessError):
            versions[runtime] = "not_available"
    LOG.info("audio_runtime_versions %s", json.dumps(versions, sort_keys=True))


def cookie_diagnostics():
    result = {"catalog_authenticated": bool(CATALOG.authenticated),
              "audio_cookie_file": bool(YT_DLP_COOKIE_FILE),
              "cookie_count": 0, "expired_count": 0, "session_count": 0,
              "auth_cookie_present": False}
    if YT_DLP_COOKIE_FILE:
        try:
            with open(YT_DLP_COOKIE_FILE, encoding="utf-8") as stream:
                for line in stream:
                    if line.startswith("#HttpOnly_"):
                        line = line[len("#HttpOnly_"):]
                    if line.startswith("#"):
                        continue
                    fields = line.rstrip("\r\n").split("\t")
                    if len(fields) != 7:
                        continue
                    result["cookie_count"] += 1
                    expiry = int(fields[4])
                    if expiry == 0:
                        result["session_count"] += 1
                    elif expiry <= time.time():
                        result["expired_count"] += 1
                    if fields[5] in ("SAPISID", "__Secure-1PAPISID", "__Secure-3PAPISID", "SID") and (expiry == 0 or expiry > time.time()):
                        result["auth_cookie_present"] = True
        except (OSError, ValueError):
            result["cookie_read_error"] = True
    return result


class ExtractionDiagnostics:
    """Safe yt-dlp diagnostics: never log audio URLs, cookies or token values."""

    def debug(self, message):
        message = str(message)
        if "PO Token Providers:" in message:
            LOG.info("pot_provider_plugin_discovered")
        elif "Generating a" in message and "PO Token" in message:
            LOG.info("pot_generation_requested")
        elif "Generated a" in message and "PO Token" in message:
            LOG.info("pot_generation_completed")

    def info(self, message):
        self.debug(message)

    def warning(self, message):
        reason = diagnostic_reason(message)
        if reason != "unclassified":
            LOG.warning("youtube_extraction_warning reason=%s", reason)

    def error(self, message):
        LOG.warning("youtube_extraction_error reason=%s", diagnostic_reason(message))



def prepare_browser_cookies():
    """Persist private browser cookies for yt-dlp, retaining Netscape expiries."""
    target = "/data/ytmusic-yt-dlp-cookies.txt"
    jar = CATALOG.cookie_jar
    if not jar:
        header = next((v for k, v in CATALOG.auth_headers.items()
                       if k.lower() == "cookie"), "")
        if isinstance(header, str) and header.strip():
            lines = ["# Netscape HTTP Cookie File\n"]
            for part in header.split(";"):
                if "=" not in part:
                    continue
                name, value = (x.strip() for x in part.split("=", 1))
                if (not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", name)
                        or not value or len(value) > 4096
                        or any(c in value for c in "\r\n\t")):
                    continue
                lines.append(f".youtube.com\tTRUE\t/\tTRUE\t0\t{name}\t{value}\n")
            if len(lines) > 1:
                jar = "".join(lines)
    if not jar:
        if os.path.exists(target):
            os.remove(target)
        return None
    temporary = target + ".new"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as cookie_file:
        cookie_file.write(jar)
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
    LOG.info("ytmusic_browser_session_available_for_audio")
    return target

YT_DLP_COOKIE_FILE = prepare_browser_cookies()
VIDEO_RE = re.compile(r"^/stream/([A-Za-z0-9_-]{11})\.mp3$")


def sign_url(vid, start=0):
    checked_video_id(vid)
    if type(start) is not int or not 0 <= start <= 86400:
        raise ValueError("Invalid signed stream start")
    expiry = int(time.time()) + 3600
    # Preserve compatibility with existing zero-offset signed URLs.
    payload = f"{vid}:{expiry}" if start == 0 else f"{vid}:{expiry}:{start}"
    mac = hmac.new(API_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    suffix = f"&start={start}" if start else ""
    return f"{BASE_URL}/stream/{vid}.mp3?exp={expiry}&sig={mac}{suffix}"


def validate_stream_url(vid, query):
    try:
        expiry = int((query.get("exp") or ["0"])[0])
        supplied = (query.get("sig") or [""])[0]
        start = int((query.get("start") or ["0"])[0])
    except (ValueError, TypeError):
        return False
    if not 0 <= start <= 86400 or expiry < time.time() or expiry > time.time() + 3700:
        return False
    payload = f"{vid}:{expiry}" if start == 0 else f"{vid}:{expiry}:{start}"
    expected = hmac.new(API_KEY.encode(), payload.encode(),
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied)


def _cache_get(vid):
    entry = SOURCE_CACHE.get(vid)
    if not entry or time.monotonic() - entry["time"] >= SOURCE_TTL:
        return None
    try:
        expiry = int((parse_qs(urlsplit(entry["url"]).query).get("expire") or ["0"])[0])
        if expiry and expiry < time.time() + 60:
            return None
    except (ValueError, TypeError):
        return None
    return entry


def _cache_put(vid, entry):
    SOURCE_CACHE.pop(vid, None)
    SOURCE_CACHE[vid] = entry
    while len(SOURCE_CACHE) > 15:
        SOURCE_CACHE.pop(next(iter(SOURCE_CACHE)))


def _extract_source(vid, cookiefile, warm_only=False):
    """Resolve and validate bytes, without contacting any HA receiver."""
    started = time.monotonic()
    base = {
        "quiet": True, "no_warnings": False, "noplaylist": True,
        "format": "bestaudio/best",
        "skip_download": True, "socket_timeout": 15,
        "retries": 1, "extractor_retries": 1,
        "js_runtimes": {"deno": {}, "node": {}},
        "ignore_no_formats_error": False,
        "verbose": True,
        "logger": ExtractionDiagnostics(),
    }
    if cookiefile:
        base["cookiefile"] = cookiefile
    # The selected preferred client is genuinely attempted first.
    # web_music is most useful with a signed-in browser session; without
    # cookies, let yt-dlp select its current default before falling back.
    preferred = CLIENT if CLIENT != "web_music" or cookiefile else "auto"
    ordered = [preferred, "web_music", "auto", "mweb", "tv",
               "web_safari", "web_embedded"]
    if warm_only:
        ordered = ordered[:1]
        base["socket_timeout"] = 6
        base["retries"] = 0
        base["extractor_retries"] = 0
    strategies = []
    for label in ordered:
        if any(existing == label for existing, _ in strategies):
            continue
        strategies.append((label, None if label == "auto" else [label]))
    last_error = None
    LOG.info("audio_probe_start video_id=%s cookie_status=%s", vid, json.dumps(cookie_diagnostics(), sort_keys=True))
    for label, clients in strategies:
        options = dict(base)
        if clients is not None:
            options["extractor_args"] = {"youtube": {"player_client": clients}}
        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                info = downloader.extract_info(
                    "https://www.youtube.com/watch?v=" + vid, download=False)
            url = info.get("url") if isinstance(info, dict) else None
            if not isinstance(url, str) or not url.startswith("https://"):
                raise RuntimeError("Extractor returned no HTTPS audio source")
            headers = info.get("http_headers", {}) or {}
            # A URL can exist yet return HTTP 403. Test the first 1 KiB
            # before caching, selecting it or initiating any Cast session.
            safe_headers = {k: v for k, v in headers.items()
                            if isinstance(v, str) and "\r" not in v and "\n" not in v}
            safe_headers["Range"] = "bytes=0-1023"
            try:
                with urlopen(Request(url, headers=safe_headers), timeout=6 if warm_only else 15) as check:
                    sniff = check.read(1024)
                    if check.status not in (200, 206) or not sniff:
                        raise RuntimeError("Audio server returned no bytes")
            except HTTPError as http_error:
                LOG.warning("audio_url_rejected video_id=%s strategy=%s http=%d",
                            vid, label, http_error.code)
                raise
            entry = {
                "url": url, "headers": headers, "duration": info.get("duration"),
                "strategy": label, "time": time.monotonic(),
            }
            LOG.info("source_resolved video_id=%s strategy=%s format=%s elapsed_ms=%d",
                     vid, label, info.get("format_id"),
                     (time.monotonic()-started)*1000)
            return entry
        except (yt_dlp.utils.DownloadError, RuntimeError, HTTPError,
                yt_dlp.utils.ExtractorError) as exc:
            last_error = exc
            LOG.warning("source_strategy_unavailable video_id=%s strategy=%s type=%s reason=%s",
                        vid, label, type(exc).__name__, diagnostic_reason(exc))
    raise AudioSourceUnavailable(
        "Kein abspielbarer YouTube-Audiostream gefunden. "
        "Bei YouTube kann ein PO-Token erforderlich sein."
    ) from last_error


def resolve_source(vid):
    checked_video_id(vid)
    # Reuse an already-running preparation of this exact title, not another one.
    with WARM_LOCK:
        pending = WARM_INFLIGHT.get(vid)
    if pending:
        pending.wait(timeout=3)
    with SOURCE_LOCK:
        entry = _cache_get(vid)
        if entry:
            # Older URLs may have been invalidated before their advertised expiry.
            # Recheck a tiny range before reuse, then fall back to normal extraction.
            if time.monotonic() - entry["time"] > 85:
                try:
                    headers = {k: v for k, v in entry["headers"].items()
                               if isinstance(v, str) and "\r" not in v and "\n" not in v}
                    headers["Range"] = "bytes=0-1023"
                    with urlopen(Request(entry["url"], headers=headers), timeout=4) as response:
                        if response.status not in (200, 206) or not response.read(1024):
                            raise RuntimeError("Cached audio no longer available")
                except (OSError, RuntimeError, HTTPError) as exc:
                    LOG.info("source_cache_invalidated video_id=%s type=%s", vid, type(exc).__name__)
                    SOURCE_CACHE.pop(vid, None)
                    entry = None
            if entry:
                LOG.info("source_cache_hit video_id=%s age_ms=%d", vid, (time.monotonic()-entry["time"])*1000)
                return entry["url"], entry["headers"]
        entry = _extract_source(vid, YT_DLP_COOKIE_FILE)
        _cache_put(vid, entry)
        return entry["url"], entry["headers"]


def warm_source(vids):
    """Prepare up to four candidates in order, using a single background worker."""
    global WARM_PENDING, WARM_RUNNING
    if isinstance(vids, str):
        vids = [vids]
    candidates = list(dict.fromkeys(checked_video_id(vid) for vid in vids))[:4]
    with WARM_LOCK:
        now = time.monotonic()
        WARM_PENDING = [v for v in candidates if v not in WARM_INFLIGHT
                        and now - WARM_LAST.get(v, -1000) >= 90]
        if WARM_RUNNING or not WARM_PENDING:
            return
        WARM_RUNNING = True

    def worker():
        global WARM_PENDING, WARM_RUNNING
        while True:
            with WARM_LOCK:
                if not WARM_PENDING:
                    WARM_RUNNING = False
                    return
                candidate = WARM_PENDING.pop(0)
                now = time.monotonic()
                if now - WARM_LAST.get(candidate, -1000) < 90:
                    continue
                WARM_LAST[candidate] = now
                for k in list(WARM_LAST):
                    if now - WARM_LAST[k] > 300:
                        del WARM_LAST[k]
                event = threading.Event()
                WARM_INFLIGHT[candidate] = event
            try:
                with tempfile.TemporaryDirectory(prefix="yt-warm-") as tmp:
                    if not SOURCE_LOCK.acquire(blocking=False):
                        with WARM_LOCK:
                            WARM_LAST.pop(candidate, None)
                        continue
                    try:
                        if _cache_get(candidate):
                            with WARM_LOCK:
                                WARM_LAST.pop(candidate, None)
                            continue
                        epoch = SOURCE_EPOCH
                        copy = None
                        if YT_DLP_COOKIE_FILE:
                            copy = os.path.join(tmp, "cookies.txt")
                            shutil.copyfile(YT_DLP_COOKIE_FILE, copy)
                            os.chmod(copy, 0o600)
                    finally:
                        SOURCE_LOCK.release()
                    entry = _extract_source(candidate, copy, warm_only=True)
                    with SOURCE_LOCK:
                        if epoch == SOURCE_EPOCH and not _cache_get(candidate):
                            _cache_put(candidate, entry)
                            LOG.info("source_prefetched video_id=%s", candidate)
            except Exception as exc:
                LOG.info("source_prefetch_skipped video_id=%s type=%s", candidate, type(exc).__name__)
            finally:
                with WARM_LOCK:
                    WARM_INFLIGHT.pop(candidate, None)
                    event.set()
    threading.Thread(target=worker, daemon=True, name="audio-source-prefetch").start()


PLAYER = Playback(CATALOG, sign_url, str(OPTIONS.get(
    "player_entity", "media_player.ultra_slim_soundbar")))

from yt_mqtt import MusicMqttBridge
MUSIC_BRIDGE = MusicMqttBridge(lambda: CATALOG, PLAYER, resolve_source, warm_source=warm_source)


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
            return self.json_reply(200, {"ok": True, "version": "0.2.44",
                                         "player_client": CLIENT,
                                         "api_auth": True})
        stream = VIDEO_RE.fullmatch(path)
        if stream:
            vid = stream.group(1)
            if not validate_stream_url(vid, args):
                return self.json_reply(403, {"error": "invalid stream link"})
            start = int((args.get("start") or ["0"])[0])
            if head:
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Connection", "close")
                self.end_headers()
                return
            return self.stream(vid, start)
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
                result = {"ytmusic_account_connected": CATALOG.authenticated,
                          "audio_browser_session": bool(YT_DLP_COOKIE_FILE),
                          "browser_login_available": True}
            elif path == "/api/diagnostics":
                result = cookie_diagnostics()
                try:
                    result["playlist_access_verified"] = bool(CATALOG.library_playlists(1))
                except Exception as exc:
                    result["playlist_access_verified"] = False
                    result["catalog_error_reason"] = diagnostic_reason(exc)
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
            elif path == "/api/audio-level":
                result = {"gain_db": AUDIO_LEVEL.gain}
            elif path == "/api/measure-audio":
                vid = checked_video_id((args.get("video_id") or [""])[0])
                start = max(0, min(3600, int((args.get("start") or ["45"])[0])))
                duration = max(10, min(30, int((args.get("duration") or ["25"])[0])))
                if not LEVEL_PROBE_SLOT.acquire(blocking=False):
                    return self.json_reply(429, {"error": "measurement already running"})
                try:
                    url, headers = resolve_source(vid)
                    result = {"video_id": vid, "start_seconds": start,
                              "duration_seconds": duration, **measure(url, headers, start, duration)}
                    LOG.info("audio_level_measured video_id=%s rms_dbfs=%.1f lufs=%.1f peak_dbfs=%.1f",
                             vid, result["rms_dbfs"], result["integrated_lufs"], result["peak_dbfs"])
                finally:
                    LEVEL_PROBE_SLOT.release()
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
                result = {
                    "video_id": vid, "http_status": status,
                    "bytes_received": received,
                    "po_token_in_url": "pot" in parse_qs(urlsplit(url).query),
                    "source_strategy": SOURCE_CACHE.get(vid, {}).get("strategy"),
                    "elapsed_ms": int((time.monotonic()-started)*1000),
                }
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
            if path == "/api/auth/reload":
                # Called only by the HA Ingress session manager, with API key.
                # A fresh catalog replaces the old one only after validation.
                global CATALOG, YT_DLP_COOKIE_FILE, SOURCE_EPOCH
                new_catalog = load_catalog()
                with SOURCE_LOCK:
                    CATALOG = new_catalog
                    PLAYER.catalog = new_catalog
                    SOURCE_EPOCH += 1
                    SOURCE_CACHE.clear()
                    with WARM_LOCK:
                        WARM_PENDING.clear()
                        WARM_LAST.clear()
                    YT_DLP_COOKIE_FILE = prepare_browser_cookies()
                result = {"connected": CATALOG.authenticated,
                          "audio_browser_session": bool(YT_DLP_COOKIE_FILE)}
            elif path == "/api/audio-level":
                result = AUDIO_LEVEL.set(body.get("gain_db"))
                LOG.info("audio_gain_configured gain_db=%.1f", AUDIO_LEVEL.gain)
            elif path == "/api/play":
                if body.get("video_id"):
                    vid = checked_video_id(body["video_id"])
                    track = {"video_id": vid, "title": str(body.get("title") or vid),
                             "artist": body.get("artist") or "",
                             "thumbnail": body.get("thumbnail"),
                             "duration_seconds": body.get("duration_seconds")}
                    selected_by_search = False
                else:
                    results = CATALOG.search(body.get("query", ""), limit=5)
                    if not results:
                        raise ValueError("No YouTube Music songs match the query")
                    track, selected_by_search = results[0], True
                # Warm the short-lived audio URL before instructing the Cast receiver.
                resolve_source(track["video_id"])
                if not isinstance(track.get("duration_seconds"), int):
                    with SOURCE_LOCK:
                        metadata_duration = SOURCE_CACHE.get(track["video_id"], {}).get("duration")
                    if isinstance(metadata_duration, (int, float)) and metadata_duration > 0:
                        track["duration_seconds"] = round(metadata_duration)
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
            elif path == "/api/auto_continue":
                # Settings only; never opens an audio source or calls Cast.
                result = PLAYER.set_auto_continue(body.get("enabled"))
            elif path == "/api/seek":
                result = PLAYER.seek(body.get("position"))
            elif path == "/api/external_stop":
                # Caller already stopped the Cast target; don't restart or stop it again.
                result = PLAYER.external_stop()
            elif path == "/api/queue/play":
                result = PLAYER.play_queued(body.get("index"), body.get("video_id"))
            elif path == "/api/history/play":
                result = PLAYER.play_history(body.get("index"), body.get("video_id"))
            elif path == "/api/queue/remove":
                result = PLAYER.queue_remove(body.get("index"))
            elif path == "/api/queue/move":
                result = PLAYER.queue_move(body.get("from_index"), body.get("to_index"))
            elif path == "/api/queue/clear":
                result = PLAYER.queue_clear()
            elif path == "/api/playlist":
                playlist_id = checked_playlist_id(body.get("playlist_id"))
                playlist = CATALOG.playlist(playlist_id,
                                            limit=int(body.get("limit", 100)))
                tracks = playlist["tracks"]
                if not tracks:
                    raise ValueError("Playlist contains no playable songs")
                if body.get("shuffle") or PLAYER.shuffle_enabled:
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
            elif path == "/api/previous":
                result = PLAYER.previous()
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
        except AudioSourceUnavailable as exc:
            LOG.warning("audio_source_blocked path=%s", path)
            return self.json_reply(503, {"error": str(exc)})
        except Exception as exc:
            LOG.error("api_post_failed path=%s error=%s", path, type(exc).__name__)
            return self.json_reply(502, {"error": "playback request failed"})

    def stream(self, vid, start=0):
        if not STREAM_SLOTS.acquire(blocking=False):
            return self.json_reply(429, {"error": "too many simultaneous streams"})
        started = time.monotonic()
        proc = None
        try:
            source, source_headers = resolve_source(vid)
            command = input_args(source, source_headers, start)
            command += ["-loglevel", "error"] + AUDIO_LEVEL.filter_args()
            command.extend(["-c:a", "libmp3lame", "-b:a", "128k", "-f", "mp3",
                            "-flush_packets", "1", "pipe:1"])
            LOG.info("stream_audio_gain video_id=%s gain_db=%.1f", vid, AUDIO_LEVEL.gain)
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
        except AudioSourceUnavailable:
            LOG.warning("stream_audio_source_blocked video_id=%s", vid)
            try:
                current = (PLAYER.status().get("current") or {}).get("video_id")
                if current == vid:
                    PLAYER.external_stop()
            except Exception:
                LOG.warning("failed_to_clear_queue_after_stream_error")
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
    log_runtime_versions()
    LOG.info("audio_cookie_status %s", json.dumps(cookie_diagnostics(), sort_keys=True))
    LOG.info("server_started version=0.2.44 player_client=%s player=%s",
             CLIENT, PLAYER.entity_id)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever(poll_interval=0.25)
