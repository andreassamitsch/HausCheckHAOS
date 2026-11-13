"""YouTube Music metadata/catalog adapter; no media-stream extraction here."""
import json
import logging
import re
import threading
from ytmusicapi import YTMusic

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
    }


def normalize_playlist(item):
    if not isinstance(item, dict):
        return None
    pid = item.get("playlistId") or item.get("id") or item.get("browseId")
    if isinstance(pid, str) and pid.startswith("VL"):
        pid = pid[2:]
    if not isinstance(pid, str) or not PLAYLIST_ID_RE.fullmatch(pid):
        return None
    return {"playlist_id": pid, "title": str(item.get("title") or pid),
            "count": item.get("count") or item.get("trackCount")}


class Catalog:
    def __init__(self, auth_json=""):
        self.lock = threading.RLock()
        self.authenticated = False
        auth = None
        if auth_json:
            try:
                auth = json.loads(auth_json)
                if not isinstance(auth, dict) or "Cookie" not in auth:
                    raise ValueError("Expected YouTube Music browser headers JSON with Cookie")
                self.authenticated = True
            except (ValueError, TypeError) as exc:
                raise ValueError("Invalid ytmusic_auth_json: " + str(exc)) from exc
        self.api = YTMusic(auth=auth, language="de", location="AT")
        LOG.info("catalog_started authenticated=%s", self.authenticated)

    def search(self, query, kind="songs", limit=10):
        if not isinstance(query, str) or not (1 <= len(query.strip()) <= 150):
            raise ValueError("Query must contain 1-150 characters")
        if kind not in ("songs", "videos", "playlists"):
            raise ValueError("kind must be songs, videos or playlists")
        count = max(1, min(int(limit), 30))
        with self.lock:
            raw = self.api.search(query.strip(), filter=kind, limit=count)
        normalize = normalize_playlist if kind == "playlists" else normalize_track
        tracks = [t for r in raw if (t := normalize(r)) is not None][:count]
        if kind == "songs" and not tracks:
            # Some guest sessions return an empty "songs" shelf but valid music videos.
            with self.lock:
                fallback = self.api.search(query.strip(), filter="videos", limit=count)
            tracks = [t for r in fallback if (t := normalize_track(r)) is not None][:count]
            LOG.info("song_search_fallback kind=videos count=%d", len(tracks))
        return tracks

    def playlist(self, playlist_id, limit=100):
        checked_playlist_id(playlist_id)
        with self.lock:
            raw = self.api.get_playlist(playlist_id, limit=max(1, min(int(limit), 200)))
        tracks = [t for r in raw.get("tracks", []) if (t := normalize_track(r)) is not None]
        return {"playlist_id": playlist_id, "title": str(raw.get("title") or playlist_id),
                "tracks": tracks}

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
