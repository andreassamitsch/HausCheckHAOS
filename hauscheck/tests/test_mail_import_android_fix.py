from __future__ import annotations

import unittest

from fastapi.responses import HTMLResponse

from app.mail_import_android_fix import (
    _filename_with_extension,
    _looks_like_eml,
    _relax_import_page,
    _sniff_extension,
)


class MailImportAndroidFixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.eml = (
            b"Delivered-To: andi@example.com\r\n"
            b"From: Iris <iris@example.com>\r\n"
            b"To: andi@example.com\r\n"
            b"Subject: Hausangebot\r\n"
            b"MIME-Version: 1.0\r\n"
            b"Content-Type: multipart/mixed; boundary=test\r\n"
            b"\r\n--test--\r\n"
        )

    def test_gmail_eml_is_detected_with_generic_android_mime(self) -> None:
        self.assertTrue(_looks_like_eml(self.eml))
        self.assertEqual(_sniff_extension(self.eml, "application/octet-stream"), ".eml")
        self.assertEqual(_sniff_extension(self.eml, "text/plain"), ".eml")

    def test_rfc822_mime_restores_missing_extension(self) -> None:
        self.assertEqual(_sniff_extension(b"", "message/rfc822"), ".eml")
        self.assertEqual(_filename_with_extension("Nachricht.bin", ".eml"), "Nachricht.eml")
        self.assertEqual(_filename_with_extension("Nachricht", ".eml"), "Nachricht.eml")

    def test_supported_binary_signatures_are_detected(self) -> None:
        self.assertEqual(_sniff_extension(b"%PDF-1.7\n", "application/octet-stream"), ".pdf")
        self.assertEqual(_sniff_extension(b"\xff\xd8\xff\xe0", "application/octet-stream"), ".jpg")
        self.assertEqual(_sniff_extension(b"\x89PNG\r\n\x1a\n", "application/octet-stream"), ".png")
        self.assertIsNone(_sniff_extension(b"not a supported file", "application/octet-stream"))

    def test_android_file_picker_filter_is_relaxed(self) -> None:
        original = HTMLResponse(
            '<input type="file" accept=".eml,message/rfc822,application/pdf">'
            '<p>Beide .eml-Dateien können gleichzeitig gewählt werden.</p>'
        )
        fixed = _relax_import_page(original)
        html = fixed.body.decode("utf-8")
        self.assertIn('accept="*/*"', html)
        self.assertIn("HausCheck erkennt sie sicher anhand des Inhalts", html)


if __name__ == "__main__":
    unittest.main()
