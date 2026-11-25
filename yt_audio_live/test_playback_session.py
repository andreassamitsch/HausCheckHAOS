"""Receiver-free regression tests for retained playback and seeking."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
import playback


def track(i):
    return {"video_id": f"test{i:07d}", "title": f"Track {i}", "duration_seconds": 180}


class QueueSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.files = patch.multiple(playback,
            SESSION_FILE=Path(self.tmp.name) / "last.json",
            AUTOCONTINUE_FILE=Path(self.tmp.name) / "preferences.json")
        self.files.start()
        self.addCleanup(self.files.stop)
        self.thread = patch.object(playback.threading.Thread, "start")
        self.thread.start()
        self.addCleanup(self.thread.stop)
        self.catalog = Mock()
        self.p = self.player()

    def player(self):
        p = playback.Playback(self.catalog, lambda v, offset=0: f"http://test/{v}?offset={offset}", "media_player.test")
        p._service = Mock()
        return p

    def test_stop_and_restart_restore_without_autoplay(self):
        self.p.start(track(1), [track(2), track(3)])
        self.p.seek(65)
        self.p.stop()
        s = self.p.status()
        self.assertEqual(s["cast_state"], "stopped")
        self.assertEqual(s["media_position"], 65)
        self.assertEqual(s["queue_length"], 2)
        self.assertEqual(s["current"]["video_id"], track(1)["video_id"])
        p = self.player()
        p._service.assert_not_called()
        self.assertEqual(p.status()["queue_length"], 2)
        self.assertEqual(p.status()["media_position"], 65)
        p.resume()
        self.assertIn("offset=65", p._service.call_args.args[1]["media_content_id"])

    def test_external_stop_does_not_advance(self):
        self.p.start(track(1), [track(2), track(3)])
        self.p._service.reset_mock()
        old_generation = self.p.generation
        self.p.external_stop()
        self.p._advance("ended", expected_generation=old_generation)
        self.p._service.assert_not_called()
        self.assertEqual(self.p.status()["queue_length"], 2)

    def test_queue_selection_and_new_session(self):
        self.p.start(track(1), [track(2), track(3)])
        self.p.stop()
        self.p.play_queued(1, track(3)["video_id"])
        self.assertEqual(self.p.status()["queue"][0]["video_id"], track(2)["video_id"])
        self.assertEqual(self.p.status()["history_length"], 1)
        self.p.start(track(4))
        self.assertEqual(self.p.status()["queue_length"], 0)
        self.assertEqual(self.p.status()["history_length"], 0)

    def test_seek_while_paused_does_not_play_until_resume(self):
        self.p.start(track(1), [track(2)])
        self.p.last_player_state = "paused"
        self.p._service.reset_mock()
        self.p.seek(110)
        self.p._service.assert_not_called()
        self.assertEqual(self.p.status()["media_position"], 110)
        self.p.resume()
        self.assertIn("offset=110", self.p._service.call_args.args[1]["media_content_id"])
        self.assertEqual(self.p.status()["queue_length"], 1)

    def test_stopped_seek_and_resume(self):
        self.p.start(track(1), [track(2)])
        self.p.external_stop()
        self.p._service.reset_mock()
        self.p.seek(30)
        self.p._service.assert_not_called()
        self.p.resume()
        self.assertIn("offset=30", self.p._service.call_args.args[1]["media_content_id"])

    def test_natural_end_retains_history_without_auto_continue(self):
        self.p.set_auto_continue(False)
        self.p.start(track(1), [track(2)])
        self.p.next()
        self.p._advance("ended", expected_generation=self.p.generation)
        self.assertEqual(self.p.status()["cast_state"], "stopped")
        self.assertEqual(self.p.status()["history_length"], 1)
        self.assertEqual(self.p.status()["current"]["video_id"], track(2)["video_id"])


if __name__ == "__main__":
    unittest.main()
