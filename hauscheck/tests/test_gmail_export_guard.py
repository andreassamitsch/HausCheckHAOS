from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI

from app import gmail_exchange


class GmailExportGuardTests(unittest.TestCase):
    def _settings(self, *, legacy_auto_send: bool = False) -> gmail_exchange.GmailExchangeSettings:
        return gmail_exchange.GmailExchangeSettings(
            enabled=True,
            auto_send_on_import=legacy_auto_send,
            username="sender@example.com",
            app_password="test-only",
            to="receiver@example.com",
        )

    def test_manual_send_remains_available_when_automatic_send_is_disabled(self) -> None:
        settings = self._settings(legacy_auto_send=False)
        self.assertTrue(settings.send_ready)

    def test_implicit_or_legacy_automatic_send_does_not_send(self) -> None:
        for legacy_auto_send in (False, True):
            with self.subTest(legacy_auto_send=legacy_auto_send):
                with (
                    patch.object(gmail_exchange, "load_gmail_settings", return_value=self._settings(legacy_auto_send=legacy_auto_send)),
                    patch.object(gmail_exchange, "get_house") as get_house,
                    patch.object(gmail_exchange, "create_analysis_zip") as create_zip,
                    patch.object(gmail_exchange, "_send_mail_sync") as send_mail,
                ):
                    sent = asyncio.run(gmail_exchange.send_analysis_zip_via_gmail("d8de0dc6"))
                    self.assertFalse(sent)
                    get_house.assert_not_called()
                    create_zip.assert_not_called()
                    send_mail.assert_not_called()

    def test_explicit_manual_send_works_with_automatic_send_disabled(self) -> None:
        with (
            patch.object(gmail_exchange, "load_gmail_settings", return_value=self._settings()),
            patch.object(gmail_exchange, "get_house", return_value={"id": "d8de0dc6"}),
            patch.object(gmail_exchange, "create_analysis_zip", return_value=Path("export.zip")) as create_zip,
            patch.object(gmail_exchange, "_send_mail_sync") as send_mail,
        ):
            sent = asyncio.run(gmail_exchange.send_analysis_zip_via_gmail("d8de0dc6", manual=True))
            self.assertTrue(sent)
            create_zip.assert_called_once_with("d8de0dc6")
            send_mail.assert_called_once()

    def test_manual_endpoint_explicitly_opts_in(self) -> None:
        app = FastAPI()
        gmail_exchange.register_gmail_exchange(app)
        route = next(r for r in app.routes if getattr(r, "path", None) == "/houses/{house_id}/gmail-send")
        with (
            patch.object(gmail_exchange, "get_house", return_value={"id": "d8de0dc6"}),
            patch.object(gmail_exchange, "send_analysis_zip_via_gmail", new_callable=AsyncMock) as send_mail,
        ):
            response = asyncio.run(route.endpoint("d8de0dc6"))
            self.assertEqual(303, response.status_code)
            send_mail.assert_awaited_once_with("d8de0dc6", manual=True)

    def test_automatic_ingest_and_refresh_use_only_github_export(self) -> None:
        app_dir = Path(__file__).resolve().parents[1] / "app"
        for name in ("import_patch.py", "candidate_preimport_dedupe.py"):
            with self.subTest(source=name):
                source = (app_dir / name).read_text(encoding="utf-8")
                self.assertIn("auto_export_house_to_github(", source)
                self.assertNotIn("send_analysis_zip_via_gmail(", source)


if __name__ == "__main__":
    unittest.main()
