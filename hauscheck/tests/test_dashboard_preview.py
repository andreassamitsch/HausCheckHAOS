from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.house_merge as house_merge
import app.mobile_first_ui as mobile_first_ui


class DashboardPreviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        local_root = patch.object(house_merge, "PROJECTS_DIR", self.root)
        local_root.start()
        self.addCleanup(local_root.stop)
        self.house_id = "house-1"

    def image(self, media_id: str, original_url: str = "") -> dict:
        path = self.root / self.house_id / "images" / f"{media_id}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test image bytes")
        return {
            "id": media_id,
            "kind": "image",
            "download_status": "downloaded",
            "house_id": self.house_id,
            "original_url": original_url,
            "local_path": str(path),
            "created_at": "2026-10-20T10:00:00Z",
        }

    def render(self, house: dict, items: list[dict]) -> str:
        with (
            patch.object(house_merge, "get_house", return_value=house),
            patch.object(house_merge, "list_media", return_value=items),
        ):
            return house_merge.preview_for_dashboard(house)

    def test_existing_gallery_replaces_blocked_remote_hotlink(self) -> None:
        house = {
            "id": self.house_id,
            "preview_image_url": "https://broker.example/blocked-preview.jpg",
        }
        html = self.render(house, [self.image("stored")])
        self.assertIn('src="media/stored"', html)
        self.assertNotIn("broker.example", html)

    def test_explicitly_selected_local_cover_wins(self) -> None:
        house = {
            "id": self.house_id,
            "preview_media_id": "selected",
            "preview_image_url": "https://broker.example/cover.jpg",
        }
        html = self.render(house, [self.image("first"), self.image("selected")])
        self.assertIn('src="media/selected"', html)
        self.assertIn('alt="Ausgewähltes Vorschaubild"', html)

    def test_downloaded_portal_preview_wins_if_not_explicitly_selected(self) -> None:
        url = "https://broker.example/original.jpg"
        house = {"id": self.house_id, "preview_image_url": url}
        html = self.render(house, [self.image("other"), self.image("portal", url)])
        self.assertIn('src="media/portal"', html)
        self.assertNotIn('src="https://', html)

    def test_stale_selected_and_missing_file_use_remaining_local_image(self) -> None:
        house = {
            "id": self.house_id,
            "preview_media_id": "missing",
            "preview_image_url": "https://broker.example/cover.jpg",
        }
        stale = self.image("missing")
        Path(stale["local_path"]).unlink()
        html = self.render(house, [stale, self.image("available")])
        self.assertIn('src="media/available"', html)

    def test_invalid_local_path_cannot_be_served_as_preview(self) -> None:
        house = {"id": self.house_id, "preview_image_url": ""}
        unsafe = self.image("unsafe")
        unsafe["local_path"] = "/etc/passwd"
        self.assertIn("Noch kein Bild", self.render(house, [unsafe]))

    def test_remote_fallback_only_when_no_local_gallery_image(self) -> None:
        house = {"id": self.house_id, "preview_image_url": "https://broker.example/cover.jpg"}
        self.assertIn('src="https://broker.example/cover.jpg"', self.render(house, []))
        self.assertIn("Noch kein Bild", self.render({"id": self.house_id}, []))

    def test_house_header_uses_local_image_instead_of_broker_hotlink(self) -> None:
        house = {
            "id": self.house_id,
            "preview_image_url": "https://broker.example/blocked.jpg",
        }
        with patch.object(mobile_first_ui, "_ordered_images", return_value=[self.image("gallery")]):
            self.assertEqual(mobile_first_ui._hero_src(house), "../media/gallery")

    def test_house_header_respects_downloaded_portal_cover(self) -> None:
        house = {
            "id": self.house_id,
            "preview_image_url": "https://broker.example/matching.jpg",
        }
        images = [self.image("other"), self.image("match", house["preview_image_url"])]
        with patch.object(mobile_first_ui, "_ordered_images", return_value=images):
            self.assertEqual(mobile_first_ui._hero_src(house), "../media/match")


if __name__ == "__main__":
    unittest.main()
