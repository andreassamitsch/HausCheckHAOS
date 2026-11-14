"""Queue, radio and Home Assistant Cast control. Separate from YouTube catalog."""
import json
import logging
import os
import random
import threading
import time
from collections import deque
from urllib.request import Request, urlopen

from music_catalog import checked_video_id

LOG = logging.getLogger("yt_audio_live.playback")
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
HA_API = "http://supervisor/core/api"


class Playback:
    def __init__(self, catalog, stream_url, entity_id):
        if not entity_id.startswith("media_player."):
            raise ValueError("player_entity must be a media_player")
        self.catalog = catalog
        self.stream_url = stream_url
        self.entity_id = entity_id
        self.lock = threading.RLock()
        self.current = None
        self.queue = deque()
        self.radio_enabled = False
        self.radio_prefetching = False
        self.seen = deque(maxlen=250)
        self.started_at = 0
        self.playing_seen = False
        self.last_player_state = "unknown"
        self.last_error = None
        self.generation = 0
        self._poller = threading.Thread(target=self._poll, name="cast-monitor", daemon=True)
        self._poller.start()

    def _request(self, path, data=None):
        if not SUPERVISOR_TOKEN:
            raise RuntimeError("SUPERVISOR_TOKEN is unavailable; enable homeassistant_api")
        headers = {"Authorization": "Bearer " + SUPERVISOR_TOKEN,
                   "Content-Type": "application/json"}
        body = json.dumps(data).encode() if data is not None else None
        request = Request(HA_API + path, data=body, headers=headers,
                          method="POST" if data is not None else "GET")
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read(160000) or b"null")

    def _service(self, name, data=None):
        return self._request("/services/media_player/" + name,
                             {"entity_id": self.entity_id, **(data or {})})

    def _cast_state(self):
        state = self._request("/states/" + self.entity_id)
        return str(state.get("state") or "unknown")

    def status(self):
        with self.lock:
            return {
                "current": dict(self.current) if self.current else None,
                "queue": [dict(x) for x in list(self.queue)[:50]],
                "queue_length": len(self.queue),
                "radio_enabled": self.radio_enabled,
                "radio_prefetching": self.radio_prefetching,
                "cast_state": self.last_player_state,
                "cast_seen_playing": self.playing_seen,
                "last_error": self.last_error,
                "player_entity": self.entity_id,
            }

    @staticmethod
    def _minimal_track(track):
        if not isinstance(track, dict):
            raise ValueError("Track must be an object")
        vid = checked_video_id(track.get("video_id"))
        return {"video_id": vid,
                "title": str(track.get("title") or vid)[:200],
                "artist": str(track.get("artist") or "")[:150],
                "duration_seconds": track.get("duration_seconds")
                                    if isinstance(track.get("duration_seconds"), int)
                                    else None}

    def enqueue(self, tracks):
        items = [self._minimal_track(x) for x in tracks]
        if not items:
            raise ValueError("No playable tracks")
        with self.lock:
            if len(self.queue) + len(items) > 200:
                raise ValueError("Queue limit is 200 songs")
            self.queue.extend(items)
            return self.status()

    def start(self, track, rest=(), radio=False):
        first = self._minimal_track(track)
        rest = [self._minimal_track(t) for t in rest][:199]
        with self.lock:
            self.generation += 1
            gen = self.generation
            self.queue = deque(rest)
            self.current = first
            self.seen = deque([first["video_id"]], maxlen=250)
            self.radio_enabled = bool(radio)
            self.started_at = time.monotonic()
            self.playing_seen = False
            self.last_player_state = "starting"
            self.last_error = None
        try:
            self._play(first, gen)
        except Exception as exc:
            with self.lock:
                if self.generation == gen:
                    self.current = None
                    self.last_error = str(exc)[:300]
            raise
        self._prefetch_radio()
        return self.status()

    def _play(self, track, generation):
        LOG.info("starting_track video_id=%s title=%r", track["video_id"], track["title"])
        url = self.stream_url(track["video_id"])
        self._service("play_media", {"media_content_id": url,
                                     "media_content_type": "audio/mpeg"})
        with self.lock:
            if generation == self.generation:
                self.started_at = time.monotonic()
                self.last_player_state = "starting"

    def _advance(self, reason="next"):
        with self.lock:
            previous = self.current
            if self.queue:
                first = self.queue.popleft()
                self.current = first
                self.seen.append(first["video_id"])
                self.generation += 1
                gen = self.generation
                self.started_at = time.monotonic()
                self.playing_seen = False
                self.last_player_state = "starting"
            else:
                first = None
                gen = None
        if first is None:
            if self.radio_enabled and previous:
                try:
                    suggestions = self.catalog.radio(previous["video_id"], limit=25)
                    self.enqueue(self._unseen(suggestions))
                except Exception as exc:
                    LOG.warning("radio_fallback_failed error=%s", type(exc).__name__)
            with self.lock:
                if not self.queue:
                    self.current = None
                    self.radio_enabled = False
                    self.generation += 1
                    if reason == "next":
                        self._service("media_stop")
                    return self.status()
            return self._advance(reason=reason)
        try:
            self._play(first, gen)
        except Exception as exc:
            LOG.error("next_track_failed video_id=%s reason=%s error=%s",
                      first["video_id"], reason, type(exc).__name__)
            with self.lock:
                if self.generation == gen:
                    self.current = None
                    self.last_error = str(exc)[:300]
            raise
        self._prefetch_radio()
        return self.status()

    def next(self):
        return self._advance("next")

    def stop(self):
        with self.lock:
            self.generation += 1
            self.current = None
            self.queue.clear()
            self.radio_enabled = False
            self.playing_seen = False
        self._service("media_stop")
        return self.status()

    def pause(self):
        self._service("media_pause")
        return self.status()

    def resume(self):
        self._service("media_play")
        return self.status()

    def set_radio(self, enabled=True, seed=None):
        if seed:
            checked_video_id(seed)
        with self.lock:
            if not self.current:
                raise ValueError("Play a song before enabling radio")
            self.radio_enabled = bool(enabled)
            if not enabled:
                return self.status()
        self._prefetch_radio(seed=seed)
        return self.status()

    def _unseen(self, tracks):
        with self.lock:
            ids = set(self.seen)
            ids.update(t["video_id"] for t in self.queue)
            if self.current:
                ids.add(self.current["video_id"])
        result = []
        for item in tracks:
            if item["video_id"] not in ids:
                result.append(item)
                ids.add(item["video_id"])
        return result

    def _prefetch_radio(self, seed=None):
        with self.lock:
            if not self.radio_enabled or not self.current or self.radio_prefetching:
                return
            if len(self.queue) >= 6:
                return
            target = seed or self.current["video_id"]
            self.radio_prefetching = True

        def work():
            try:
                songs = self.catalog.radio(target, limit=25)
                items = self._unseen(songs)
                with self.lock:
                    if self.radio_enabled and self.current:
                        for item in items[:max(0, 70 - len(self.queue))]:
                            self.queue.append(self._minimal_track(item))
                        LOG.info("radio_added count=%d seed=%s", len(items), target)
            except Exception as exc:
                LOG.warning("radio_fetch_failed seed=%s error=%s", target,
                            type(exc).__name__)
                with self.lock:
                    self.last_error = "Radio recommendations unavailable"
            finally:
                with self.lock:
                    self.radio_prefetching = False

        threading.Thread(target=work, name="radio-prefetch", daemon=True).start()

    def _poll(self):
        while True:
            time.sleep(2.5)
            with self.lock:
                if not self.current:
                    continue
                generation = self.generation
                started = self.started_at
            try:
                state = self._cast_state()
            except Exception as exc:
                LOG.debug("cast_poll_failed error=%s", type(exc).__name__)
                continue
            advance = False
            with self.lock:
                if generation != self.generation or not self.current:
                    continue
                self.last_player_state = state
                if state == "playing":
                    self.playing_seen = True
                elif state in ("idle", "off") and self.playing_seen:
                    advance = time.monotonic() - started >= 5
            if advance:
                LOG.info("track_finished_detected auto_next=1")
                try:
                    self._advance("ended")
                except Exception as exc:
                    LOG.error("auto_next_failed error=%s", type(exc).__name__)
