from __future__ import annotations

import unittest

from fastapi.responses import HTMLResponse

from app.mail_inbox_route_fix import _fix_detail_page, _fix_inbox_page


class MailInboxRouteFixTests(unittest.TestCase):
    def test_inbox_refresh_and_item_links_are_bound_to_current_ingress_path(self) -> None:
        original = HTMLResponse(
            '<form method="post" action="mail-inbox/refresh"></form>'
            '<a href="mail-inbox/abc123">Öffnen</a>'
        )
        fixed = _fix_inbox_page(original)
        html = fixed.body.decode("utf-8")

        self.assertIn('data-hc-mail-action="refresh"', html)
        self.assertIn('data-hc-mail-item="abc123"', html)
        self.assertIn("window.location.pathname.replace", html)
        self.assertIn("root + '/refresh'", html)
        self.assertNotIn('action="mail-inbox/refresh"', html)
        self.assertNotIn('href="mail-inbox/abc123"', html)

    def test_detail_actions_keep_the_item_id_and_ingress_prefix(self) -> None:
        original = HTMLResponse(
            '<a href="../mail-inbox">Posteingang</a>'
            '<form method="post" action="assign"></form>'
            '<form method="post" action="ignore"></form>'
        )
        fixed = _fix_detail_page(original)
        html = fixed.body.decode("utf-8")

        self.assertIn('data-hc-mail-back="1"', html)
        self.assertIn('data-hc-mail-suffix="/assign"', html)
        self.assertIn('data-hc-mail-suffix="/ignore"', html)
        self.assertIn("current + (form.dataset.hcMailSuffix", html)
        self.assertNotIn('action="assign"', html)
        self.assertNotIn('action="ignore"', html)


if __name__ == "__main__":
    unittest.main()
