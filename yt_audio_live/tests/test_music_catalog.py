import sys
import unittest
from pathlib import Path
from unittest.mock import call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from music_catalog import Catalog


SONG = {"resultType": "song", "videoId": "ZUtAe5PUKtE", "title": "Mad World"}
VIDEO = {"resultType": "video", "videoId": "etSbOs3aUqI", "title": "Mad World (Video)"}


class CatalogSearchTests(unittest.TestCase):
    @patch("music_catalog.YTMusic")
    def test_filtered_songs_need_only_one_search(self, ytmusic):
        search = ytmusic.return_value.search
        search.return_value = [SONG]
        results = Catalog().search(" mad world ", limit=5)
        self.assertEqual([track["video_id"] for track in results], [SONG["videoId"]])
        search.assert_called_once_with("mad world", filter="songs", limit=5)

    @patch("music_catalog.YTMusic")
    def test_songs_in_mixed_search_take_precedence_over_videos(self, ytmusic):
        search = ytmusic.return_value.search
        search.side_effect = [[], [VIDEO, SONG]]
        results = Catalog().search("mad world", limit=5)
        self.assertEqual([track["video_id"] for track in results], [SONG["videoId"]])
        self.assertEqual(search.call_args_list, [
            call("mad world", filter="songs", limit=5), call("mad world", limit=5),
        ])

    @patch("music_catalog.YTMusic")
    def test_videos_are_available_when_neither_search_finds_songs(self, ytmusic):
        search = ytmusic.return_value.search
        search.side_effect = [[], [VIDEO], [VIDEO]]
        results = Catalog().search("mad world", limit=5)
        self.assertEqual([track["video_id"] for track in results], [VIDEO["videoId"]])
        search.assert_called_with("mad world", filter="videos", limit=5)
