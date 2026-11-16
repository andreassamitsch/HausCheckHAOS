from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image

from app import new_listing_email as alerts
from app.gmail_exchange import GmailExchangeSettings


class NewListingEmailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.database = Path(self.directory.name) / "test.sqlite"
        self.connection_patch = patch.object(alerts, "connect", side_effect=self._connect)
        self.connection_patch.start()
        alerts.ensure_notification_schema()

    def tearDown(self) -> None:
        self.connection_patch.stop()
        self.directory.cleanup()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _candidate(candidate_id: str, *, status: str = "new", url: str = "https://www.willhaben.at/iad/immobilien/haus-kaufen/test-12345678", house_id: str | None = None) -> dict:
        return {
            "id": candidate_id,
            "title": "Ein schönes Haus in Wies",
            "status": status,
            "source_url": url,
            "price_eur": 275000,
            "living_area_m2": 120,
            "plot_area_m2": 1000,
            "preview_image_url": "https://images.willhaben.at/one.jpg",
            "imported_house_id": house_id,
        }

    def _queue(self, candidate: dict, prior: set[str] | None = None) -> int:
        with (
            patch.object(alerts, "get_search_profile", return_value={"name": "Häuser Wies"}),
            patch.object(alerts, "list_search_candidates", return_value=[candidate]),
            patch.object(alerts, "source_url_exists", return_value=False),
            patch.object(alerts, "_cached_images", return_value=[
                "https://images.willhaben.at/one.jpg", "https://images.willhaben.at/two.jpg",
            ]),
        ):
            return alerts._enqueue_new_candidates("profile-1", prior or set())

    def test_only_first_discovery_is_queued_even_with_tracking_url(self) -> None:
        candidate = self._candidate("fresh")
        self.assertEqual(1, self._queue(candidate))
        same_offer_other_query = self._candidate("other-profile", url=candidate["source_url"] + "?utm_source=email")
        self.assertEqual(0, self._queue(same_offer_other_query))
        with self._connect() as db:
            row = db.execute("SELECT payload_json FROM new_listing_notifications").fetchone()
        self.assertIsNotNone(row)
        self.assertIn("two.jpg", row["payload_json"])

    def test_prior_candidates_and_reactivated_or_filtered_not_queued(self) -> None:
        self.assertEqual(0, self._queue(self._candidate("existing"), {"existing"}))
        self.assertEqual(0, self._queue(self._candidate("filtered", status="filtered")))
        self.assertEqual(0, self._queue(self._candidate("rejected", status="rejected")))
        self.assertEqual(0, self._queue(self._candidate("changed", status="changed")))
        self.assertEqual(0, self._queue(self._candidate("merged", house_id="known")))
        with (
            patch.object(alerts, "get_search_profile", return_value={"name": "Haus"}),
            patch.object(alerts, "list_search_candidates", return_value=[self._candidate("known")]),
            patch.object(alerts, "source_url_exists", return_value=True),
        ):
            self.assertEqual(0, alerts._enqueue_new_candidates("profile-1", set()))

    def test_review_candidate_is_not_lost(self) -> None:
        self.assertEqual(1, self._queue(self._candidate("review", status="review")))

    def test_canonicalization_and_untrusted_image_links(self) -> None:
        self.assertEqual(
            alerts._listing_key("https://www.willhaben.at/iad/foo-12345678?tracking=1"),
            alerts._listing_key("https://www.willhaben.at/iad/foo-12345678"),
        )
        self.assertIsNone(alerts._safe_image_url("http://localhost/img.jpg"))
        self.assertIsNone(alerts._safe_image_url("https://127.0.0.1/img.jpg"))
        self.assertIsNone(alerts._safe_image_url("https://internal.local/img.jpg"))
        self.assertIsNotNone(alerts._safe_image_url("https://images.willhaben.at/photo.jpg"))

    def test_email_has_direct_link_and_two_inline_images(self) -> None:
        settings = GmailExchangeSettings(
            enabled=True,
            username="sender@example.com",
            app_password="test-only",
            to="recipient@example.com",
            auto_send_on_import=False,
        )
        data = {
            "title": "Haus in Wies",
            "url": "https://www.willhaben.at/iad/immobilien/haus-kaufen/test-12345678",
            "profile": "Suchprofil Südweststeiermark",
            "price_eur": 275000,
            "living_area_m2": 120,
            "plot_area_m2": 1000,
            "status": "new",
        }
        msg = alerts._build_notification_mail(settings, data, [("eins.jpg", b"a"), ("zwei.jpg", b"b")])
        self.assertIn("Neues Inserat:", msg["Subject"])
        self.assertNotIn("HAUSCHECK_EXPORT", msg["Subject"])
        self.assertIn(data["url"], str(msg))
        self.assertIn("275.000", str(msg))
        self.assertEqual(2, sum(part.get_content_type() == "image/jpeg" for part in msg.walk()))

    def test_converts_image_to_small_jpeg(self) -> None:
        source = Image.new("RGB", (1500, 1200), "white")
        stream = BytesIO()
        source.save(stream, format="PNG")
        data = alerts._jpeg_preview(stream.getvalue())
        with Image.open(BytesIO(data)) as image:
            self.assertEqual("JPEG", image.format)
            self.assertLessEqual(image.width, 1000)
            self.assertLessEqual(image.height, 800)

    def test_send_is_persistent_and_immediate_repeat_is_suppressed(self) -> None:
        self._queue(self._candidate("fresh"))
        settings = GmailExchangeSettings(
            enabled=True, username="sender@example.com", app_password="test",
            to="recipient@example.com", auto_send_on_import=False,
        )
        with (
            patch.object(alerts, "notifications_enabled", return_value=True),
            patch.object(alerts.gmail_exchange, "load_gmail_settings", return_value=settings),
            patch.object(alerts, "_prepare_images", new_callable=AsyncMock, return_value=[]),
            patch.object(alerts, "_send_smtp_sync") as smtp,
        ):
            self.assertEqual(1, asyncio.run(alerts.send_pending_notifications()))
            self.assertEqual(0, asyncio.run(alerts.send_pending_notifications()))
            smtp.assert_called_once()
        with self._connect() as db:
            row = db.execute("SELECT sent_at, attempts FROM new_listing_notifications").fetchone()
            self.assertIsNotNone(row["sent_at"])
            self.assertEqual(1, row["attempts"])

    def test_smtp_failure_is_retryable_but_not_in_a_tight_loop(self) -> None:
        self._queue(self._candidate("fresh"))
        settings = GmailExchangeSettings(enabled=True, username="a@example.com", app_password="test", to="b@example.com")
        with (
            patch.object(alerts, "notifications_enabled", return_value=True),
            patch.object(alerts.gmail_exchange, "load_gmail_settings", return_value=settings),
            patch.object(alerts, "_prepare_images", new_callable=AsyncMock, return_value=[]),
            patch.object(alerts, "_send_smtp_sync", side_effect=RuntimeError("offline")) as smtp,
        ):
            self.assertEqual(0, asyncio.run(alerts.send_pending_notifications()))
            self.assertEqual(0, asyncio.run(alerts.send_pending_notifications()))
            smtp.assert_called_once()
        with self._connect() as db:
            row = db.execute("SELECT sent_at, attempts, last_error FROM new_listing_notifications").fetchone()
            self.assertIsNone(row["sent_at"])
            self.assertEqual(1, row["attempts"])
            self.assertIn("offline", row["last_error"])


if __name__ == "__main__":
    unittest.main()
