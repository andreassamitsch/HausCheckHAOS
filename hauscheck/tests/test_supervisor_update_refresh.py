from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.responses import HTMLResponse

from app.supervisor_update_refresh import _inject_settings_card, reload_supervisor_store


class SupervisorUpdateRefreshTests(unittest.TestCase):
    def test_settings_page_gets_ingress_safe_reload_action(self) -> None:
        response = _inject_settings_card(HTMLResponse("<html><body><main><h1>Einstellungen</h1></main></body></html>"))
        html = response.body.decode("utf-8")

        self.assertIn("HausCheck-Updates", html)
        self.assertIn('data-hc-store-reload="1"', html)
        self.assertIn("window.location.pathname", html)
        self.assertIn("/system/reload-store", html)
        self.assertLess(html.index("HausCheck-Updates"), html.index("</main>"))

    def test_missing_supervisor_token_returns_clear_error(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(reload_supervisor_store())
        self.assertEqual(503, raised.exception.status_code)
        self.assertIn("Supervisor-Zugriff", str(raised.exception.detail))


if __name__ == "__main__":
    unittest.main()
