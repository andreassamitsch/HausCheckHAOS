"""Pure playback state regression tests: NO Home Assistant or Soundbar access."""
from __future__ import annotations

import sys
import threading
import time
import types
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

sys.modules.setdefault("music_catalog", types.SimpleNamespace(
    checked_video_id=lambda vid: vid
))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import playback


class StubCatalog:
    def radio(self, vid, limit=25):
        return []


def track(video_id="aaaaaaaaaaa", duration=180):
    return {"video_id": video_id, "title": video_id, "artist": "Test",
            "duration_seconds": duration}


class FakePlayback(playback.Playback):
    """Construct a player without creating a background thread or network."""
    def __init__(self, pos=10, duration=180):
        self.catalog = StubCatalog()
        self.stream_url = lambda vid, start=0: f"fake://{vid}/{start}"
        self.entity_id = "media_player.test_soundbar"
        self.lock = threading.RLock()
        self.current = track(duration=duration)
        self.queue = deque([track("bbbbbbbbbbb", 200)])
        self.history = deque(maxlen=50)
        self.radio_enabled = True
        self.radio_prefetching = False
        self.seen = deque(maxlen=250)
        self.started_at = time.monotonic() - 90
        self.playing_seen = True
        self.last_player_state = "playing"
        self.last_error = None
        self.generation = 3
        self.seek_offset = 0
        self.position = float(pos)
        self.position_seen = True
        self.position_observed_monotonic = time.monotonic()
        self.position_updated_at = time.time()
        self.services = []
        self.played = []

    def _service(self, name, data=None):
        self.services.append((name, data))

    def _play(self, item, gen, start_at=0):
        self.played.append((item["video_id"], start_at))

    def _prefetch_radio(self, seed=None):
        pass

    def run_one_poll(self, state="idle", content_id=None):
        self._cast_status = lambda: {
            "state": state,
            "attributes": {"media_content_id": content_id or
                "http://localhost/stream/aaaaaaaaaaa.mp3?exp=1&sig=2"}}
        count = 0
        original = playback.time.sleep
        def one_then_exit(_):
            nonlocal count
            count += 1
            if count > 1:
                raise StopIteration
        try:
            playback.time.sleep = one_then_exit
            with self.assert_stop_iteration():
                self._poll()
        finally:
            playback.time.sleep = original

    from contextlib import contextmanager
    @contextmanager
    def assert_stop_iteration(self):
        try:
            yield
        except StopIteration:
            return
        raise AssertionError("poller didn't yield on next iteration")


class PlaybackTests(unittest.TestCase):
    def test_cast_is_temporarily_idle_during_start(self):
        p = FakePlayback()
        p.last_player_state = "starting"
        p.playing_seen = False
        p.started_at = time.monotonic() - 3
        p.run_one_poll("idle")
        self.assertEqual(p.last_player_state, "starting")
        self.assertIsNotNone(p.current)
        self.assertEqual(p.played, [])
        self.assertEqual(len(p.queue), 1)

    def test_cast_is_temporarily_off_during_seek(self):
        p = FakePlayback()
        p.seek(65)
        p.run_one_poll("off")
        self.assertEqual(p.last_player_state, "starting")
        self.assertEqual(p.current["video_id"], "aaaaaaaaaaa")
        self.assertEqual(p.played, [("aaaaaaaaaaa", 65)])
        self.assertEqual(len(p.queue), 1)

    def test_cast_reports_playing_after_loading(self):
        p = FakePlayback()
        p.last_player_state = "starting"
        p.playing_seen = False
        p.started_at = time.monotonic() - 2
        p.run_one_poll("playing")
        self.assertTrue(p.playing_seen)
        self.assertEqual(p.last_player_state, "playing")

    def test_clock_advances_without_cast_position(self):
        p = FakePlayback(pos=5)
        p.position_seen = False
        p.position_observed_monotonic = time.monotonic() - 8
        p.run_one_poll("playing")
        self.assertGreaterEqual(p.position, 12.5)
        self.assertLess(p.position, 16)
        state = p.status()
        self.assertGreaterEqual(state["media_position"], 12.5)
        self.assertAlmostEqual(state["media_position_updated_at"], time.time(), delta=2)

    def test_cast_zero_position_does_not_reset_progress(self):
        p = FakePlayback(pos=15)
        p.position_seen = False
        p.position_observed_monotonic = time.monotonic() - 4
        p._cast_status = lambda: {
            "state": "playing",
            "attributes": {
                "media_position": 0,
                "media_content_id": "http://host/stream/aaaaaaaaaaa.mp3"
            }
        }
        import playback as module
        from unittest.mock import patch
        with patch.object(module.time, "sleep", side_effect=[None, StopIteration]):
            with self.assertRaises(StopIteration):
                p._poll()
        self.assertGreaterEqual(p.position, 18.5)
        self.assertEqual(p.last_player_state, "playing")

    def test_pause_freezes_fallback_clock(self):
        p = FakePlayback(pos=35)
        p.position_observed_monotonic = time.monotonic() - 6
        p.run_one_poll("paused")
        frozen = p.status()["media_position"]
        p.position_observed_monotonic -= 20
        self.assertAlmostEqual(p.status()["media_position"], frozen, delta=0.2)

    def test_seek_fallback_includes_seek_offset(self):
        p = FakePlayback(pos=35)
        p.seek(100)
        p.position_observed_monotonic = time.monotonic() - 5
        p.run_one_poll("playing")
        self.assertGreaterEqual(p.status()["media_position"], 104.5)
        self.assertLess(p.status()["media_position"], 110)
        self.assertEqual(len(p.queue), 1)

    def test_manual_stop_early_does_not_advance(self):
        p = FakePlayback(pos=60)
        p.run_one_poll("idle")
        self.assertIsNone(p.current)
        self.assertEqual(len(p.queue), 0)
        self.assertFalse(p.radio_enabled)
        self.assertEqual(p.played, [])
        self.assertEqual(p.services, [])

    def test_manual_off_near_end_is_still_stop(self):
        p = FakePlayback(pos=178)
        p.run_one_poll("off")
        self.assertIsNone(p.current)
        self.assertEqual(p.played, [])

    def test_natural_end_advances_to_queued_track(self):
        p = FakePlayback(pos=178)
        p.run_one_poll("idle")
        self.assertEqual(p.current["video_id"], "bbbbbbbbbbb")
        self.assertEqual(p.played, [("bbbbbbbbbbb", 0)])

    def test_software_stop_clears_first_then_sends_one_stop(self):
        p = FakePlayback()
        p.stop()
        self.assertEqual([x[0] for x in p.services], ["media_stop"])
        self.assertIsNone(p.current)
        p.stop()
        self.assertEqual([x[0] for x in p.services], ["media_stop"])

    def test_external_stop_never_sends_cast_command(self):
        p = FakePlayback()
        p.external_stop()
        self.assertIsNone(p.current)
        self.assertEqual(p.services, [])
        self.assertEqual(len(p.queue), 0)

    def test_resume_after_stop_rejected(self):
        p = FakePlayback()
        p.external_stop()
        with self.assertRaises(ValueError):
            p.resume()
        self.assertEqual(p.services, [])

    def test_pause_does_not_trigger_auto_next(self):
        p = FakePlayback(pos=30)
        p.run_one_poll("paused")
        self.assertEqual(p.current["video_id"], "aaaaaaaaaaa")
        self.assertEqual(len(p.queue), 1)

    def test_source_changed_stops_queue(self):
        p = FakePlayback(pos=35)
        p.run_one_poll("playing", "http://host/stream/ccccccccccc.mp3")
        self.assertIsNone(p.current)
        self.assertFalse(p.radio_enabled)

    def test_seek_preserves_queue_without_volume_touch(self):
        p = FakePlayback(pos=40)
        p.seek(78)
        self.assertEqual(p.played, [("aaaaaaaaaaa", 78)])
        self.assertEqual(len(p.queue), 1)
        self.assertTrue(p.radio_enabled)
        self.assertEqual(p.services, [])
        self.assertEqual(p.status()["media_position"], 78)

    def test_seek_validation(self):
        p = FakePlayback(pos=45)
        for value in (-1, 180, 3.5):
            with self.assertRaises(ValueError):
                p.seek(value)
        self.assertEqual(p.services, [])

    def test_select_queued_song_preserves_other_titles(self):
        p = FakePlayback()
        p.queue.extend([track("ccccccccccc", 111),track("ddddddddddd", 118)])
        p.play_queued(1, "ccccccccccc")
        self.assertEqual(p.current["video_id"], "ccccccccccc")
        self.assertEqual([x["video_id"] for x in p.queue],
                         ["bbbbbbbbbbb","ddddddddddd"])
        self.assertEqual(p.history[0]["video_id"], "aaaaaaaaaaa")
        self.assertEqual(p.played, [("ccccccccccc",0)])
        self.assertEqual(p.services, [])

    def test_queue_selection_rejects_stale_index(self):
        p = FakePlayback()
        with self.assertRaises(ValueError):
            p.play_queued(0, "ccccccccccc")
        self.assertEqual(p.played, [])
        self.assertEqual(p.current["video_id"], "aaaaaaaaaaa")

    def test_previous_track_restores_next(self):
        p = FakePlayback()
        p.history.appendleft(track("zzzzzzzzzzz", 222))
        p.previous()
        self.assertEqual(p.current["video_id"], "zzzzzzzzzzz")
        self.assertEqual(p.queue[0]["video_id"], "aaaaaaaaaaa")
        self.assertEqual(p.played, [("zzzzzzzzzzz",0)])

    def test_select_history_song_preserves_queue(self):
        p = FakePlayback()
        p.history.extend([track("xxxxxxxxyyy", 140), track("ggggggggggg",150)])
        p.play_history(1, "ggggggggggg")
        self.assertEqual(p.current["video_id"], "ggggggggggg")
        self.assertEqual(p.queue[0]["video_id"], "aaaaaaaaaaa")
        self.assertEqual(p.queue[1]["video_id"], "bbbbbbbbbbb")
        self.assertEqual(p.history[0]["video_id"], "xxxxxxxxyyy")

    def test_stop_clears_history(self):
        p = FakePlayback()
        p.history.append(track("zzzzzzzzzzz"))
        p.external_stop()
        self.assertEqual(len(p.history), 0)
        self.assertEqual(p.services, [])


if __name__ == "__main__":
    unittest.main()
