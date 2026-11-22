"""YouTube Music metadata/catalog adapter; no media-stream extraction here."""
import json
import logging
import re
import threading
import time
from ytmusicapi import YTMusic, setup
from ytmusicapi.helpers import get_authorization

LOG = logging.getLogger("yt_audio_live.catalog")
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
PLAYLIST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,200}$")


def checked_video_id(value):
    if not isinstance(value, str) or not VIDEO_ID_RE.fullmatch(value):
        raise ValueError("video_id must be exactly 11 YouTube ID characters")
    return value


def checked_playlist_id(value):
    if not isinstance(value, str) or not PLAYLIST_ID_RE.fullmatch(value):
        raise ValueError("Invalid playlist_id")
    return value


def _duration(value):
    if isinstance(value, int) and value >= 0:
        return value
    if not isinstance(value, str):
        return None
    try:
        total = 0
        for part in value.split(":"):
            total = total * 60 + int(part)
        return total if 0 < total < 24 * 3600 else None
    except ValueError:
        return None


def track_thumbnail(item, vid):
    """Use the YouTube Music artwork; fall back to a thumbnail for exact IDs."""
    entries = item.get("thumbnails") or []
    if isinstance(entries, dict):
        entries = entries.get("thumbnails") or []
    if not entries and isinstance(item.get("thumbnail"), dict):
        entries = item["thumbnail"].get("thumbnails") or []
    if isinstance(entries, list):
        for entry in reversed(entries):
            if isinstance(entry, dict):
                url = entry.get("url")
                if isinstance(url, str) and url.startswith("https://") and len(url) < 1024:
                    return url
    return "https://i.ytimg.com/vi/" + vid + "/hqdefault.jpg"


def normalize_track(item):
    if not isinstance(item, dict):
        return None
    vid = item.get("videoId")
    if not isinstance(vid, str) or not VIDEO_ID_RE.fullmatch(vid):
        return None
    artists = item.get("artists") or []
    if isinstance(artists, list):
        artist = ", ".join(x.get("name", "") for x in artists
                           if isinstance(x, dict) and x.get("name"))
    elif isinstance(artists, str):
        artist = artists
    else:
        artist = ""
    if not artist and isinstance(item.get("artist"), str):
        artist = item["artist"]
    duration = item.get("duration_seconds")
    if not isinstance(duration, int):
        duration = _duration(item.get("duration") or item.get("length"))
    return {
        "video_id": vid, "title": str(item.get("title") or vid),
        "artist": artist, "duration_seconds": duration,
        "album": (item.get("album") or {}).get("name", "") if isinstance(item.get("album"), dict)
                 else str(item.get("album") or ""),
        "thumbnail": track_thumbnail(item, vid),
    }


def normalize_playlist(item):
    if not isinstance(item, dict):
        return None
    pid = item.get("playlistId") or item.get("id") or item.get("browseId")
    if isinstance(pid, str) and pid.startswith("VL"):
        pid = pid[2:]
    if not isinstance(pid, str) or not PLAYLIST_ID_RE.fullmatch(pid):
        return None
    covers = item.get("thumbnails") or []
    if isinstance(covers, dict):
        covers = covers.get("thumbnails") or []
    cover_url = ""
    if isinstance(covers, list):
        for image in reversed(covers):
            if isinstance(image, dict) and isinstance(image.get("url"), str):
                if image["url"].startswith("https://"):
                    cover_url = image["url"]
                    break
    return {"playlist_id": pid, "title": str(item.get("title") or pid),
            "count": item.get("count") or item.get("trackCount"),
            "thumbnail": cover_url}



def parse_netscape_cookies(raw):
    """Convert a local YTDLnis/Netscape export into YTMusic headers and yt-dlp jar.

    Some Android WebViews use microseconds since 1601 for expiries, rather
    than Unix seconds; normalize those values without persisting credentials
    anywhere except the Home Assistant app private data directory.
    """
    jar = ["# Netscape HTTP Cookie File\n"]
    selected = {}
    for line in raw.splitlines():
        if not line or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        fields = line.split("\t")
        if len(fields) != 7:
            continue
        domain, subdomains, path, secure, expiry, name, value = fields
        if domain.lstrip(".").lower() not in ("youtube.com", "music.youtube.com"):
            continue
        if subdomains not in ("TRUE", "FALSE") or secure not in ("TRUE", "FALSE"):
            continue
        if not path.startswith("/") or len(path) > 512:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", name):
            continue
        if not value or len(value) > 4096 or any(ch in value for ch in "\r\n\t"):
            continue
        try:
            expiration = int(expiry)
        except ValueError:
            continue
        if expiration >= 10**15:
            # Chromium/WebView: microseconds since 1601-01-01 UTC.
            expiration = expiration // 1_000_000 - 11_644_473_600
        elif expiration >= 10**12:
            # Some exporters use Unix milliseconds.
            expiration //= 1000
        if expiration < 0 or expiration > 4_102_444_800:
            continue
        if expiration and expiration <= int(time.time()):
            continue
        jar.append("\t".join((domain, subdomains, path, secure,
                              str(expiration), name, value)) + "\n")
        # Prefer the most recent YouTube-domain cookie for duplicate names.
        selected[name] = value
    sapisid = selected.get("__Secure-3PAPISID")
    if not sapisid:
        raise ValueError("YouTube-Cookies enthalten kein __Secure-3PAPISID")
    headers = {
        "Cookie": "; ".join(f"{name}={value}" for name, value in selected.items()),
        "Content-Type": "application/json",
        "X-Goog-AuthUser": "0",
        "x-origin": "https://music.youtube.com",
        "Authorization": get_authorization(
            sapisid + " https://music.youtube.com"),
    }
    return headers, "".join(jar)


class Catalog:
    def __init__(self, auth_json=""):
        self.lock = threading.RLock()
        self.authenticated = False
        self.auth_headers = {}
        self.cookie_jar = None
        auth = None
        if auth_json and auth_json.strip():
            try:
                if auth_json.lstrip().startswith(("# Netscape HTTP Cookie File", "# HTTP Cookie File")):
                    auth, self.cookie_jar = parse_netscape_cookies(auth_json)
                else:
                    try:
                        auth = json.loads(auth_json)
                    except json.JSONDecodeError:
                        # Also accept raw /browse request headers.
                        auth = json.loads(setup(headers_raw=auth_json))
                if not isinstance(auth, dict):
                    raise ValueError("Browser headers must be a JSON object")
                auth = {str(k): v for k, v in auth.items() if isinstance(v, str)}
                cookies = next((v for k, v in auth.items() if k.lower() == "cookie"), "")
                if not cookies:
                    raise ValueError("Cookie header missing")
                self.auth_headers = auth
                self.authenticated = True
            except (ValueError, TypeError) as exc:
                raise ValueError("Invalid YTMusic browser credentials: " + str(exc)) from exc
        self.api = YTMusic(auth=auth, language="de", location="AT")
        LOG.info("catalog_started authenticated=%s", self.authenticated)

    def search(self, query, kind="songs", limit=10):
        if not isinstance(query, str) or not (1 <= len(query.strip()) <= 150):
            raise ValueError("Query must contain 1-150 characters")
        if kind not in ("songs", "videos", "playlists"):
            raise ValueError("kind must be songs, videos or playlists")
        term = query.strip()
        count = max(1, min(int(limit), 30))
        with self.lock:
            raw = self.api.search(term, filter=kind, limit=count)
        normalize = normalize_playlist if kind == "playlists" else normalize_track
        tracks = [t for r in raw if (t := normalize(r)) is not None][:count]
        if kind == "songs" and not tracks:
            # An empty filtered shelf can still have songs in the main search.
            with self.lock:
                mixed = self.api.search(term, limit=count)
            tracks = [t for r in mixed if isinstance(r, dict) and r.get("resultType") == "song"
                      and (t := normalize_track(r)) is not None][:count]
            LOG.info("song_search_fallback kind=mixed_songs count=%d", len(tracks))
            if not tracks:
                with self.lock:
                    videos = self.api.search(term, filter="videos", limit=count)
                tracks = [t for r in videos if (t := normalize_track(r)) is not None][:count]
                LOG.info("song_search_fallback kind=videos count=%d", len(tracks))
        return tracks

    def playlist(self, playlist_id, limit=100):
        checked_playlist_id(playlist_id)
        with self.lock:
            raw = self.api.get_playlist(playlist_id, limit=max(1, min(int(limit), 200)))
        tracks = [t for r in raw.get("tracks", []) if (t := normalize_track(r)) is not None]
        return {"playlist_id": playlist_id, "title": str(raw.get("title") or playlist_id),
                "tracks": tracks[:max(1, min(int(limit), 200))]}

    def library_playlists(self, limit=30):
        if not self.authenticated:
            raise ValueError("YouTube Music account not linked; public playlists work without login")
        with self.lock:
            raw = self.api.get_library_playlists(limit=max(1, min(int(limit), 100)))
        return [p for r in raw if (p := normalize_playlist(r)) is not None]

    def radio(self, video_id, limit=25):
        checked_video_id(video_id)
        with self.lock:
            result = self.api.get_watch_playlist(videoId=video_id, radio=True,
                                                 limit=max(5, min(int(limit), 50)))
        seen = {video_id}
        tracks = []
        for raw in result.get("tracks", []):
            track = normalize_track(raw)
            if track and track["video_id"] not in seen:
                tracks.append(track)
                seen.add(track["video_id"])
        return tracks
