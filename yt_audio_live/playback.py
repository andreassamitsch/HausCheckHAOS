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
        self.seek_offset = 0
        self.position = 0.0
        self.position_seen = False
        self.position_observed_monotonic = 0.0
        self.position_updated_at = time.time()
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

    def _cast_status(self):
        """Read the actual Cast media state, including its track position."""
        return self._request("/states/" + self.entity_id)

    def _cast_state(self):
        return str(self._cast_status().get("state") or "unknown")

    def status(self):
        with self.lock:
            position = self.position
            if self.current and self.position_seen and self.last_player_state == "playing":
                position += max(0.0, time.monotonic() - self.position_observed_monotonic)
            duration = (self.current or {}).get("duration_seconds")
            if isinstance(duration, (int, float)) and duration > 0:
                position = min(float(duration), position)
            return {
                "current": dict(self.current) if self.current else None,
                "queue": [dict(x) for x in list(self.queue)[:50]],
                "queue_length": len(self.queue),
                "radio_enabled": self.radio_enabled,
                "radio_prefetching": self.radio_prefetching,
                "cast_state": self.last_player_state,
                "cast_seen_playing": self.playing_seen,
                "media_position": round(position, 1) if self.current else 0,
                "media_position_updated_at": self.position_updated_at,
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
                                    else None,
                "thumbnail": str(track.get("thumbnail") or "")[:1024]
                             if str(track.get("thumbnail") or "").startswith("https://")
                             else "https://i.ytimg.com/vi/" + vid + "/hqdefault.jpg"}

    def enqueue(self, tracks):
        items = [self._minimal_track(x) for x in tracks]
        if not items:
            raise ValueError("No playable tracks")
        with self.lock:
            if len(self.queue) + len(items) > 200:
                raise ValueError("Queue limit is 200 songs")
            self.queue.extend(items)
            return self.status()

    def queue_remove(self, index):
        if type(index) is not int:
            raise ValueError("index must be an integer")
        with self.lock:
            if index < 0 or index >= len(self.queue):
                raise ValueError("queue index is out of range")
            items = list(self.queue)
            items.pop(index)
            self.queue = deque(items)
            return self.status()

    def queue_move(self, from_index, to_index):
        if type(from_index) is not int or type(to_index) is not int:
            raise ValueError("queue indices must be integers")
        with self.lock:
            items = list(self.queue)
            if not 0 <= from_index < len(items) or not 0 <= to_index < len(items):
                raise ValueError("queue index is out of range")
            item = items.pop(from_index)
            items.insert(to_index, item)
            self.queue = deque(items)
            return self.status()

    def queue_clear(self):
        with self.lock:
            self.queue.clear()
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
            self.seek_offset = 0
            self.position = 0.0
            self.position_seen = False
            self.position_observed_monotonic = 0.0
            self.position_updated_at = time.time()
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

    def _play(self, track, generation, start_at=0):
        LOG.info("starting_track video_id=%s title=%r start=%d",
                 track["video_id"], track["title"], start_at)
        url = self.stream_url(track["video_id"], start_at)
        self._service("play_media", {"media_content_id": url,
                                     "media_content_type": "audio/mpeg"})
        with self.lock:
            if generation == self.generation:
                self.started_at = time.monotonic()
                self.last_player_state = "starting"

    def _reset_position(self, offset=0):
        self.seek_offset = offset
        self.position = float(offset)
        self.position_seen = False
        self.position_observed_monotonic = 0
        self.position_updated_at = time.time()

    def _clear_playback(self, reason="external_stop"):
        """Stop our queue without issuing another Cast command."""
        with self.lock:
            had_session = self.current is not None or bool(self.queue)
            self.generation += 1
            self.current = None
            self.queue.clear()
            self.radio_enabled = False
            self.playing_seen = False
            self.last_player_state = "idle"
            self._reset_position()
        if had_session:
            LOG.info("queue_stopped reason=%s", reason)
        return self.status()

    def external_stop(self):
        """An outside media_stop/turn_off must never be treated as natural end."""
        return self._clear_playback("external_stop")

    def _advance(self, reason="next", expected_generation=None):
        with self.lock:
            if expected_generation is not None and self.generation != expected_generation:
                return self.status()
            previous = self.current
            old_generation = self.generation
            if self.queue:
                first = self.queue.popleft()
                self.current = first
                self.seen.append(first["video_id"])
                self.generation += 1
                gen = self.generation
                self.started_at = time.monotonic()
                self.playing_seen = False
                self.last_player_state = "starting"
                self._reset_position()
            else:
                first = None
                gen = None
                seed = previous["video_id"] if previous and self.radio_enabled else None
        if first is None:
            recommendations = []
            if seed:
                try:
                    recommendations = self._unseen(self.catalog.radio(seed, limit=25))
                except Exception as exc:
                    LOG.warning("radio_fallback_failed error=%s", type(exc).__name__)
            with self.lock:
                if old_generation != self.generation:
                    return self.status()
                for item in recommendations[:max(0, 70 - len(self.queue))]:
                    self.queue.append(self._minimal_track(item))
                if not self.queue:
                    self._clear_playback("queue_finished")
                    if reason == "next" and previous is not None:
                        self._service("media_stop")
                    return self.status()
            return self._advance(reason=reason, expected_generation=old_generation)
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
            active = self.current is not None
        result = self._clear_playback("api_stop")
        if active:
            self._service("media_stop")
        return result

    def seek(self, position):
        """Seek by starting the same signed audio stream at a new offset.

        Radio and upcoming titles are deliberately preserved.
        """
        if type(position) is not int:
            raise ValueError("position must be an integer number of seconds")
        with self.lock:
            track = self.current
            if track is None:
                raise ValueError("No active song")
            duration = track.get("duration_seconds")
            if type(duration) is not int or duration <= 0:
                raise ValueError("Song duration is unavailable")
            if position < 0 or position >= duration:
                raise ValueError("Seek position outside song duration")
            self.generation += 1
            generation = self.generation
            self.playing_seen = False
            self.last_player_state = "starting"
            self.started_at = time.monotonic()
            self._reset_position(position)
        self._play(track, generation, start_at=position)
        return self.status()

    def pause(self):
        with self.lock:
            if not self.current:
                raise ValueError("No active song to pause")
        self._service("media_pause")
        return self.status()

    def resume(self):
        with self.lock:
            if not self.current:
                raise ValueError("No active song to resume")
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
            generation = self.generation
            self.radio_prefetching = True

        def work():
            try:
                songs = self.catalog.radio(target, limit=25)
                items = self._unseen(songs)
                with self.lock:
                    if self.radio_enabled and self.current and self.generation == generation:
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
        """Only a real track end advances; user-initiated stop clears the app.

        Cast 'idle' is ambiguous: it also occurs on stop/disconnect, so we
        use the last reported playback position and the known song duration.
        """
        while True:
            time.sleep(2.5)
            with self.lock:
                if not self.current:
                    continue
                generation = self.generation
            try:
                result = self._cast_status()
                state = str(result.get("state") or "unknown")
                attrs = result.get("attributes") or {}
                if not isinstance(attrs, dict):
                    attrs = {}
            except Exception as exc:
                LOG.debug("cast_poll_failed error=%s", type(exc).__name__)
                continue
            action = None
            with self.lock:
                if generation != self.generation or not self.current:
                    continue
                now = time.monotonic()
                previous_state = self.last_player_state
                expected = self.current["video_id"]
                content_id = str(attrs.get("media_content_id") or "")
                # If Cast switches to another app/media, never take over its audio.
                if state == "playing" and self.playing_seen and content_id and (
                    "/stream/" + expected + ".mp3" not in content_id
                ):
                    action = "source_changed"
                self.last_player_state = state
                raw_position = attrs.get("media_position")
                if state in ("playing", "paused") and isinstance(raw_position, (int, float)) and not isinstance(raw_position, bool):
                    self.position = max(0.0, self.seek_offset + float(raw_position))
                    self.position_seen = True
                    self.position_observed_monotonic = now
                    self.position_updated_at = time.time()
                if state == "playing":
                    self.playing_seen = True
                elif state in ("idle", "off") and self.playing_seen and now - self.started_at > 4:
                    if state == "off":
                        action = "external_stop"
                    else:
                        duration = self.current.get("duration_seconds")
                        if not isinstance(duration, (int, float)) or duration <= 0:
                            duration = attrs.get("media_duration")
                        recent_position = self.position
                        if previous_state == "playing" and self.position_seen:
                            recent_position += min(3.5, max(0.0, now - self.position_observed_monotonic))
                        if isinstance(duration, (int, float)) and duration > 0:
                            # Keep this deliberately tight: stopping 20 seconds before
                            # the end must never be mistaken for finishing a song.
                            ended = self.position_seen and recent_position >= float(duration) - 4
                            if not self.position_seen and now - self.started_at >= float(duration) + 7:
                                ended = True
                        else:
                            ended = False  # unknown duration: safer to stop than skip
                        action = "ended" if ended else "external_stop"
                elif state in ("idle", "off") and not self.playing_seen and now - self.started_at > 25:
                    action = "external_stop"
            if action == "ended":
                LOG.info("track_finished_detected auto_next=1")
                try:
                    self._advance("ended", expected_generation=generation)
                except Exception as exc:
                    LOG.error("auto_next_failed error=%s", type(exc).__name__)
            elif action:
                LOG.info("cast_stopped auto_next=0 reason=%s", action)
                with self.lock:
                    if generation == self.generation:
                        self._clear_playback(action)
