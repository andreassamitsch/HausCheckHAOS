from __future__ import annotations

import io
import tempfile
import unittest
from email import policy
from email.message import EmailMessage
from pathlib import Path

from PIL import Image
from pypdf import PdfWriter

from app.mail_import import SavedInput, _evidence, _pick_fields, _process_saved_inputs


class MailImportTests(unittest.TestCase):
    def _jpeg(self) -> bytes:
        image = Image.new("RGB", (640, 480))
        pixels = image.load()
        for y in range(image.height):
            for x in range(image.width):
                pixels[x, y] = ((x * 3 + y) % 256, (y * 5 + x) % 256, (x + y * 2) % 256)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=92)
        return buffer.getvalue()

    def _pdf(self) -> bytes:
        buffer = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.write(buffer)
        return buffer.getvalue()

    def test_nested_email_import_reads_body_inline_image_and_pdf(self) -> None:
        message = EmailMessage(policy=policy.default)
        message["From"] = "Iris <iris@example.com>"
        message["To"] = "andi@example.com"
        message["Subject"] = "Fwd: Haus in Eichegg/Wies"
        message["Message-ID"] = "<fixture@example.com>"
        message.make_mixed()

        related = EmailMessage(policy=policy.default)
        related.make_related()
        alternative = EmailMessage(policy=policy.default)
        alternative.set_content(
            "Objektadresse: Eichegg 51a, 8542 Wies\n"
            "Kaufpreis: EUR 320.000\n"
            "HWB: 306,1"
        )
        alternative.add_alternative(
            "<p>Objektadresse: <b>Eichegg 51a, 8542 Wies</b></p>",
            subtype="html",
        )
        related.attach(alternative)

        image_part = EmailMessage(policy=policy.default)
        image_part.set_content(
            self._jpeg(),
            maintype="image",
            subtype="jpeg",
            filename="IMG_9815.jpg",
            disposition="inline",
            cid="<photo-1>",
        )
        related.attach(image_part)
        message.attach(related)

        pdf_part = EmailMessage(policy=policy.default)
        pdf_part.set_content(
            self._pdf(),
            maintype="application",
            subtype="pdf",
            filename="Grundbuch_Dokument-167.pdf",
            disposition="attachment",
        )
        message.attach(pdf_part)

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            mail_path = base / "haus.eml"
            mail_path.write_bytes(message.as_bytes(policy=policy.default))
            session_dir = base / "session"
            session_dir.mkdir()
            manifest = _process_saved_inputs(
                session_dir,
                [SavedInput(mail_path.name, mail_path, "message/rfc822", "direct:test", "Direkt")],
            )

        self.assertEqual(manifest["fields"]["location_text"], "Eichegg 51a, 8542 Wies")
        self.assertEqual(manifest["fields"]["price_eur"], 320000)
        self.assertAlmostEqual(manifest["fields"]["energy_hwb"], 306.1)
        self.assertTrue(any(item["classification"] == "Objektfoto" for item in manifest["artifacts"]))
        self.assertTrue(any(item["classification"] == "Grundbuchauszug" for item in manifest["artifacts"]))
        self.assertFalse(any("Keine eindeutig geeigneten Objektfotos" in warning for warning in manifest["warnings"]))

    def test_decimal_hwb_and_missing_decimal_are_conflicting(self) -> None:
        _, warnings = _pick_fields(
            [
                _evidence("energy_hwb", 306.1, "a", "Quelle A", "HWB 306,1", "high"),
                _evidence("energy_hwb", 3061, "b", "Quelle B", "HWB 3061", "high"),
            ],
            [],
        )
        self.assertTrue(any("energy_hwb" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()
