from __future__ import annotations

import tempfile
import unittest
from email import policy
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch

import app.mail_inbox as mail_inbox


class MailInboxTests(unittest.TestCase):
    def _message(self) -> bytes:
        message = EmailMessage(policy=policy.default)
        message["From"] = "Iris <iris@example.com>"
        message["To"] = "hauscheck@hauscheck.pro"
        message["Subject"] = "Fwd: Unterlagen Haus Eichegg 1"
        message["Message-ID"] = "<eichegg-1@example.com>"
        message.set_content(
            "Objektadresse: Eichegg 1, 8542 Wies\n"
            "Kaufpreis: EUR 320.000\n"
            "HWB: 95,4"
        )
        message.add_attachment(
            b"%PDF-1.4\n%test\n",
            maintype="application",
            subtype="pdf",
            filename="Unterlagen.pdf",
        )
        return message.as_bytes(policy=policy.default)

    def test_forward_prefix_is_only_a_new_house_title_hint(self) -> None:
        self.assertEqual(
            mail_inbox._strip_forward_prefix("WG: Fwd: Haus Eichegg 1"),
            "Haus Eichegg 1",
        )
        self.assertEqual(
            mail_inbox._strip_forward_prefix("AW: Unterlagen zum Objekt"),
            "Unterlagen zum Objekt",
        )

    def test_captured_message_remains_unassigned_until_user_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch.object(mail_inbox, "INBOX_ROOT", root):
                meta, created = mail_inbox._capture_raw_message(self._message(), "42")
                manifest = mail_inbox._load_json(root / meta["id"] / "manifest.json")

                self.assertTrue(created)
                self.assertEqual(meta["status"], "pending")
                self.assertIsNone(meta["assigned_house_id"])
                self.assertTrue((root / meta["id"] / "uploads" / "original.eml").exists())
                self.assertTrue(manifest.get("artifacts"))
                self.assertEqual(manifest.get("inbox_id"), meta["id"])

                duplicate, created_again = mail_inbox._capture_raw_message(self._message(), "42")
                self.assertFalse(created_again)
                self.assertEqual(duplicate["id"], meta["id"])

    def test_new_house_data_is_only_created_after_manual_choice(self) -> None:
        manifest = {
            "fields": {
                "location_text": "Eichegg 1, 8542 Wies",
                "price_eur": 320000,
                "energy_hwb": 95.4,
            }
        }
        data = mail_inbox._new_house_data("Haus Eichegg 1", manifest)
        self.assertEqual(data["title"], "Haus Eichegg 1")
        self.assertEqual(data["status"], "new")
        self.assertEqual(data["price_eur"], 320000)
        self.assertEqual(data["energy_hwb"], 95.4)


if __name__ == "__main__":
    unittest.main()
