"""Queue, radio and Home Assistant Cast control. Separate from YouTube catalog."""
import json
import logging
import os
import random
import threading
import time
from pathlib import Path
from collections import deque
from urllib.request import Request, urlopen

from music_catalog import checked_video_id

LOG = logging.getLogger("yt_audio_live.playback")
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
HA_API = "http://supervisor/core/api"
AUTOCONTINUE_FILE = Path("/data/ytmusic-playback-preferences.json")
SESSION_FILE = Path("/data/ytmusic-last-queue.json")


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
        self.history = deque(maxlen=200)
        self.radio_enabled = False
        # Distinct from explicit Radio mode: use suggestions only after the
        # existing playlist/queue has naturally reached its end.
        self.auto_continue_enabled = self._load_auto_continue_preference()
        self.shuffle_enabled = False
        self.repeat_mode = "off"  # off | all | one
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
        self._session_signature = None
        self._deferred_seek = False
        self._restore_session()
        self._poller = threading.Thread(target=self._poll, name="cast-monitor", daemon=True)
        self._poller.start()

    def _restore_session(self):
        """Restore metadata only. Never issue a receiver command at startup."""
        try:
            data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            if data.get("current"):
                self.current = self._minimal_track(data["current"])
            self.queue = deque(self._minimal_track(t) for t in data.get("queue", [])[:200])
            self.history = deque((self._minimal_track(t) for t in data.get("history", [])[:200]), maxlen=200)
            self.radio_enabled = data.get("radio_enabled") is True
            self.shuffle_enabled = data.get("shuffle_enabled") is True
            if data.get("repeat_mode") in ("off", "all", "one"):
                self.repeat_mode = data["repeat_mode"]
            saved_output = data.get("player_entity")
            if isinstance(saved_output, str) and saved_output.startswith("media_player."):
                self.entity_id = saved_output
            self.seen = deque([t["video_id"] for t in self.history] + ([self.current["video_id"]] if self.current else []), maxlen=250)
            if self.current:
                duration = self.current.get("duration_seconds") or 86400
                self._reset_position(max(0, min(int(data.get("position", 0)), duration)))
                self.last_player_state = "stopped"
                LOG.info("last_queue_restored upcoming=%d history=%d autoplay=0", len(self.queue), len(self.history))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, AttributeError, KeyError, OverflowError) as exc:
            LOG.warning("last_queue_restore_failed type=%s", type(exc).__name__)
            self.current = None
            self.queue.clear()
            self.history.clear()

    def _persist_session(self, position):
        """Atomic, private checkpoint; do not write on every polling tick."""
        data = {"current": self.current, "queue": list(self.queue),
                "history": list(self.history), "position": int(position),
                "player_entity": self.entity_id, "radio_enabled": self.radio_enabled,
                "shuffle_enabled": self.shuffle_enabled, "repeat_mode": self.repeat_mode}
        signature = json.dumps({**data, "stopped": self.last_player_state == "stopped", "position": int(position) if self.last_player_state == "stopped" or self._deferred_seek else int(position) // 30 * 30}, sort_keys=True)
        if signature == self._session_signature:
            return
        try:
            tmp = SESSION_FILE.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as file:
                os.chmod(tmp, 0o600)
                json.dump(data, file, ensure_ascii=False)
            os.replace(tmp, SESSION_FILE)
            self._session_signature = signature
        except OSError as exc:
            LOG.warning("last_queue_save_failed type=%s", type(exc).__name__)

    @staticmethod
    def _load_auto_continue_preference():
        """Default ON for first install, preserve an explicit user choice."""
        try:
            value = json.loads(AUTOCONTINUE_FILE.read_text(encoding="utf-8"))
            return value.get("auto_continue_enabled") is not False
        except FileNotFoundError:
            return True
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            LOG.warning("auto_continue_preference_read_failed type=%s",
                        type(exc).__name__)
            return True

    def set_auto_continue(self, enabled):
        if type(enabled) is not bool:
            raise ValueError("auto_continue_enabled must be boolean")
        with self.lock:
            self.auto_continue_enabled = enabled
            # Persist without resetting the current queue or triggering Cast.
            try:
                AUTOCONTINUE_FILE.parent.mkdir(parents=True, exist_ok=True)
                tmp = AUTOCONTINUE_FILE.with_suffix(".tmp")
                with open(tmp, "w", encoding="utf-8") as file:
                    os.chmod(tmp, 0o600)
                    json.dump({"auto_continue_enabled": enabled}, file)
                os.replace(tmp, AUTOCONTINUE_FILE)
                os.chmod(AUTOCONTINUE_FILE, 0o600)
            except OSError as exc:
                LOG.warning("auto_continue_preference_save_failed type=%s",
                            type(exc).__name__)
            LOG.info("auto_continue_setting enabled=%s autoplay_started=0", enabled)
        return self.status()

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
            updated_at = self.position_updated_at
            # Cast may expose no media_position (or repeatedly report 0).
            # Keep a monotonic local clock in sync with the last polling
            # observation. Its timestamp must describe the *same instant*
            # as the returned position, or HA's progress bar double-counts.
            if (self.current and self.last_player_state == "playing"
                    and self.playing_seen):
                # Count only audible playback, never an initial Cast buffer.
                position += max(0.0, time.monotonic() - self.position_observed_monotonic)
                updated_at = time.time()
            duration = (self.current or {}).get("duration_seconds")
            if isinstance(duration, (int, float)) and duration > 0:
                position = min(float(duration), position)
            self._persist_session(position)
            return {
                "current": dict(self.current) if self.current else None,
                "queue": [dict(x) for x in list(self.queue)[:200]],
                "queue_length": len(self.queue),
                "history": [dict(x) for x in self.history],
                "history_length": len(self.history),
                "radio_enabled": self.radio_enabled,
                "auto_continue_enabled": self.auto_continue_enabled,
                "shuffle_enabled": self.shuffle_enabled,
                "repeat_mode": self.repeat_mode,
                "radio_prefetching": self.radio_prefetching,
                "cast_state": self.last_player_state,
                "cast_seen_playing": self.playing_seen,
                "media_position": round(position, 1) if self.current else 0,
                "media_position_updated_at": updated_at,
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

    def set_output(self, entity_id):
        """Select a sink without sending play/stop/volume commands to any device."""
        if not isinstance(entity_id, str) or not entity_id.startswith("media_player."):
            raise ValueError("Invalid media_player")
        with self.lock:
            if self.current is not None and self.last_player_state != "stopped" and entity_id != self.entity_id:
                raise ValueError("Stop current playback before changing output")
            self.entity_id = entity_id
        LOG.info("output_selected entity_id=%s autoplay=0", entity_id)
        return self.status()

    def set_shuffle(self, enabled):
        with self.lock:
            self.shuffle_enabled = bool(enabled)
            if self.shuffle_enabled and len(self.queue)>1:
                songs = list(self.queue)
                random.SystemRandom().shuffle(songs)
                self.queue = deque(songs)
        return self.status()

    def set_repeat(self, mode):
        if mode not in ("off", "one", "all"):
            raise ValueError("repeat must be off, one or all")
        with self.lock:
            self.repeat_mode = mode
        return self.status()

    def start(self, track, rest=(), radio=False):
        first = self._minimal_track(track)
        rest = [self._minimal_track(t) for t in rest][:199]
        with self.lock:
            if self.shuffle_enabled and len(rest)>1:
                random.SystemRandom().shuffle(rest)
            self.generation += 1
            gen = self.generation
            self.queue = deque(rest)
            self._deferred_seek = False
            self.history.clear()
            self.current = first
            self.seen = deque([first["video_id"]], maxlen=250)
            self.radio_enabled = bool(radio)
            self.started_at = time.monotonic()
            self.playing_seen = False
            self.last_player_state = "starting"
            self.seek_offset = 0
            self.position = 0.0
            self.position_seen = False
            self.position_observed_monotonic = time.monotonic()
            self.position_updated_at = time.time()
            self.last_error = None
        try:
            self._play(first, gen)
        except Exception as exc:
            with self.lock:
                if self.generation == gen:
                    self.last_player_state = "stopped"
                    self.playing_seen = False
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
        self._deferred_seek = False
        self.seek_offset = offset
        self.position = float(offset)
        self.position_seen = False
        self.position_observed_monotonic = time.monotonic()
        self.position_updated_at = time.time()

    def _clear_playback(self, reason="external_stop"):
        """Disarm auto-next, retain the last queue and playback position."""
        with self.lock:
            had_session = self.current is not None or bool(self.queue)
            if self.current and self.last_player_state == "playing" and self.playing_seen:
                self.position += max(0.0, time.monotonic() - self.position_observed_monotonic)
            duration = (self.current or {}).get("duration_seconds")
            if isinstance(duration, int) and duration > 0:
                self.position = min(float(duration), self.position)
            self.generation += 1
            self._deferred_seek = False
            self.playing_seen = False
            self.last_player_state = "stopped"
            self.position_observed_monotonic = time.monotonic()
            self.position_updated_at = time.time()
            result = self.status()
        if had_session:
            LOG.info("queue_retained reason=%s upcoming=%d autoplay=0", reason, result["queue_length"])
        return result

    def external_stop(self):
        """An outside media_stop/turn_off must never be treated as natural end."""
        return self._clear_playback("external_stop")

    def _advance(self, reason="next", expected_generation=None):
        with self.lock:
            if expected_generation is not None and self.generation != expected_generation:
                return self.status()
            if reason == "ended" and self.last_player_state == "stopped":
                return self.status()
            self._deferred_seek = False
            previous = self.current
            old_generation = self.generation
            if reason=="ended" and previous and self.repeat_mode=="one":
                self.generation += 1
                generation=self.generation
                self.started_at=time.monotonic()
                self.playing_seen=False
                self.last_player_state="starting"
                self._reset_position()
                repeat_track=previous
            else:
                repeat_track=None
            wrapped = False
            if repeat_track is None and not self.queue and previous and self.repeat_mode=="all":
                # history is stored newest-first; reverse to original order.
                cycle = list(reversed(self.history)) + [previous]
                if self.shuffle_enabled and len(cycle)>1:
                    random.SystemRandom().shuffle(cycle)
                self.queue.extend(cycle)
                self.history.clear()
                wrapped = True
            if repeat_track is not None:
                first=None
                gen=None
                seed=None
            elif self.queue:
                first = self.queue.popleft()
                if previous and not wrapped:
                    self.history.appendleft(previous)
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
                # Never restart after a manual stop: stop/external_stop disarms
                # playback and increments generation. This path is reached only
                # from a natural song end or an explicit "next" click.
                seed = (previous["video_id"] if previous
                        and (self.radio_enabled or self.auto_continue_enabled)
                        and reason in ("ended", "next") else None)
        if repeat_track is not None:
            self._play(repeat_track, generation)
            return self.status()
        if first is None:
            recommendations = []
            if seed:
                try:
                    recommendations = self._unseen(self.catalog.radio(seed, limit=25))
                    LOG.info("queue_autocontinue_requested mode=%s suggestions=%d",
                             "radio" if self.radio_enabled else "automatic",
                             len(recommendations))
                except Exception as exc:
                    LOG.warning("queue_autocontinue_failed error=%s", type(exc).__name__)
            if seed and recommendations and reason == "ended":
                # This recommendation lookup may take several seconds. If
                # the output was turned off, paused or switched during that
                # time, fail closed instead of reviving the receiver.
                try:
                    receiver = self._cast_status()
                    receiver_state = str(receiver.get("state") or "unknown")
                except Exception as exc:
                    receiver_state = "unavailable"
                    LOG.warning("autocontinue_receiver_check_failed type=%s",
                                type(exc).__name__)
                if receiver_state != "idle":
                    with self.lock:
                        if old_generation == self.generation:
                            self._clear_playback("receiver_not_idle_after_recommendations")
                    return self.status()
            with self.lock:
                if old_generation != self.generation:
                    return self.status()
                # A user might disable Autoplay or stop while the provider
                # request is in flight; never resurrect playback afterward.
                if not self.radio_enabled and not self.auto_continue_enabled:
                    recommendations = []
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
                    self.last_player_state = "stopped"
                    self.playing_seen = False
                    self.last_error = str(exc)[:300]
            raise
        self._prefetch_radio()
        return self.status()

    def next(self):
        return self._advance("next")

    def previous(self):
        """Replay the previous track, leaving the following queue intact."""
        with self.lock:
            if not self.current or not self.history:
                raise ValueError("No previous song available")
            previous = self.history.popleft()
            self.queue.appendleft(self.current)
            self.current = previous
            self.generation += 1
            generation = self.generation
            self.started_at = time.monotonic()
            self.playing_seen = False
            self.last_player_state = "starting"
            self._reset_position()
        self._play(previous, generation)
        self._prefetch_radio()
        return self.status()

    def play_queued(self, index, video_id):
        """Select an existing queued song, retaining all other upcoming songs."""
        checked_video_id(video_id)
        if type(index) is not int:
            raise ValueError("queue index must be an integer")
        with self.lock:
            if not self.current or not 0 <= index < len(self.queue):
                raise ValueError("Requested song is no longer in the queue")
            items = list(self.queue)
            first = items[index]
            if first["video_id"] != video_id:
                raise ValueError("Queue changed; reload the media browser")
            items.pop(index)
            self.queue = deque(items)
            self.history.appendleft(self.current)
            self.current = first
            self.seen.append(first["video_id"])
            self.generation += 1
            generation = self.generation
            self.started_at = time.monotonic()
            self.playing_seen = False
            self.last_player_state = "starting"
            self._reset_position()
        self._play(first, generation)
        self._prefetch_radio()
        return self.status()

    def play_history(self, index, video_id):
        """Select a previous song while preserving current queue."""
        checked_video_id(video_id)
        if type(index) is not int:
            raise ValueError("history index must be an integer")
        with self.lock:
            if not self.current or not 0 <= index < len(self.history):
                raise ValueError("Requested song is no longer in history")
            items = list(self.history)
            first = items[index]
            if first["video_id"] != video_id:
                raise ValueError("History changed; reload the media browser")
            items.pop(index)
            self.history = deque(items, maxlen=200)
            self.queue.appendleft(self.current)
            self.current = first
            self.seen.append(first["video_id"])
            self.generation += 1
            generation = self.generation
            self.started_at = time.monotonic()
            self.playing_seen = False
            self.last_player_state = "starting"
            self._reset_position()
        self._play(first, generation)
        self._prefetch_radio()
        return self.status()

    def stop(self):
        with self.lock:
            active = self.current is not None and self.last_player_state != "stopped"
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
            if self.last_player_state in ("stopped", "paused"):
                self._reset_position(position)
                self._deferred_seek = self.last_player_state == "paused"
                return self.status()
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
            if not self.current or self.last_player_state == "stopped":
                raise ValueError("No active song to pause")
        self._service("media_pause")
        return self.status()

    def resume(self):
        with self.lock:
            if not self.current:
                raise ValueError("No active song to resume")
            reopen = self.last_player_state == "stopped" or self._deferred_seek
            if reopen:
                track = self.current
                offset = int(self.position)
                duration = track.get("duration_seconds")
                if isinstance(duration, int) and offset >= duration - 1:
                    offset = 0
                self._deferred_seek = False
                self.generation += 1
                generation = self.generation
                self.playing_seen = False
                self.last_player_state = "starting"
                self.started_at = time.monotonic()
                self._reset_position(offset)
        if reopen:
            try:
                self._play(track, generation, start_at=offset)
            except Exception:
                with self.lock:
                    if generation == self.generation:
                        self.last_player_state = "stopped"
                        self.playing_seen = False
                raise
        else:
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
            if not self.radio_enabled or not self.current or self.radio_prefetching or self.last_player_state == "stopped":
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
        """Only a real track end advances; user-initiated stop disarms playback.

        Cast 'idle' is ambiguous: it also occurs on stop/disconnect, so we
        use the last reported playback position and the known song duration.
        """
        while True:
            time.sleep(2.5)
            with self.lock:
                if not self.current or self.last_player_state == "stopped":
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
                if previous_state == "starting" and not self.playing_seen and state in ("playing", "paused") and content_id and "/stream/" + expected + ".mp3" not in content_id and now - self.started_at < 25:
                    continue
                # If Cast switches to another app/media, never take over its audio.
                if state in ("playing", "paused") and content_id and (
                    "/stream/" + expected + ".mp3" not in content_id
                ):
                    action = "source_changed"
                # A new Cast stream can briefly report idle/off before
                # the first audio packet reaches the receiver (especially
                # after seeking). Preserve "starting" in that short window
                # so the native HA transport controls remain visible.
                # Existing post-playback stop detection is left unchanged.
                awaiting_first_audio = (
                    previous_state in ("starting", "buffering")
                    and not self.playing_seen
                    and state in ("idle", "off", "unknown", "buffering")
                    and now - self.started_at < 25
                )
                if action == "source_changed":
                    self._clear_playback(action)
                    continue
                self.last_player_state = "starting" if awaiting_first_audio else state
                raw_position = attrs.get("media_position")
                if state in ("playing", "paused") and not (state == "paused" and self._deferred_seek):
                    # Advance our own clock even when Cast does not expose
                    # a position, or repeatedly sends a stale zero. Pause
                    # freezes the clock; seeking resets the offset first.
                    # First 'playing' observation marks when audio actually
                    # began; the previous 'starting' interval was buffering.
                    # When going from playing to paused, include the final
                    # partial interval, then freeze the clock.
                    if previous_state == "playing" and self.playing_seen:
                        self.position += max(0.0, now - self.position_observed_monotonic)
                    if (isinstance(raw_position, (int, float))
                            and not isinstance(raw_position, bool)
                            and float(raw_position) >= 0):
                        measured = self.seek_offset + float(raw_position)
                        # Cast sometimes sends 0 for the entire stream. Do
                        # not roll back a locally advancing position.
                        self.position = max(self.position, measured)
                        self.position_seen = self.position_seen or measured > self.seek_offset
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
                            # Without a trustworthy Cast position, use the
                            # locally advanced clock up to this poll. The last
                            # ~2.5 seconds may have elapsed since the previous
                            # observation, so include recent_position too.
                            if not self.position_seen and previous_state == "playing" and recent_position >= float(duration) - 3:
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
