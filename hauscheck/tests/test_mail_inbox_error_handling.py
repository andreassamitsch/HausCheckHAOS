from __future__ import annotations

import imaplib
import socket
import unittest

from app.mail_inbox_error_handling import friendly_mail_error


class MailInboxErrorHandlingTests(unittest.TestCase):
    def test_gmail_authentication_failure_is_actionable(self) -> None:
        error = imaplib.IMAP4.error(b"[AUTHENTICATIONFAILED] Invalid credentials (Failure)")
        message = friendly_mail_error(error)

        self.assertIn("16-stelliges Google-App-Passwort", message)
        self.assertIn("nicht das normale Google-Passwort", message)
        self.assertNotIn("Internal Server Error", message)

    def test_dns_failure_is_explained(self) -> None:
        message = friendly_mail_error(socket.gaierror("Name or service not known"))
        self.assertIn("IMAP-Servername", message)

    def test_unknown_error_is_safely_truncated(self) -> None:
        message = friendly_mail_error(RuntimeError("x" * 600))
        self.assertTrue(message.startswith("Postfachprüfung fehlgeschlagen:"))
        self.assertLess(len(message), 350)


if __name__ == "__main__":
    unittest.main()
