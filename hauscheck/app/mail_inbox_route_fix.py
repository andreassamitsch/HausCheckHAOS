from __future__ import annotations

import inspect
import re
from typing import Any, Callable

from fastapi import FastAPI
from fastapi.responses import HTMLResponse


def _methods(route: Any) -> set[str]:
    return set(getattr(route, "methods", set()) or set())


def _take_route(app: FastAPI, path: str, method: str) -> Callable[..., Any] | None:
    for route in list(app.router.routes):
        if getattr(route, "path", "") == path and method in _methods(route):
            app.router.routes.remove(route)
            return getattr(route, "endpoint", None)
    return None


async def _call(endpoint: Callable[..., Any], **kwargs: Any) -> Any:
    result = endpoint(**kwargs)
    return await result if inspect.isawaitable(result) else result


def _html_response(response: HTMLResponse, html: str) -> HTMLResponse:
    headers = {
        key: value
        for key, value in response.headers.items()
        if key.casefold() not in {"content-length", "content-type"}
    }
    return HTMLResponse(html, status_code=response.status_code, headers=headers)


def _inject_script(html: str, script: str) -> str:
    block = f"<script>{script}</script>"
    return html.replace("</body>", block + "</body>", 1) if "</body>" in html else html + block


def _fix_inbox_page(response: Any) -> Any:
    if not isinstance(response, HTMLResponse):
        return response
    html = response.body.decode(response.charset or "utf-8", errors="replace")
    html = html.replace(
        'action="mail-inbox/refresh"',
        'action="" data-hc-mail-action="refresh"',
    )
    html = re.sub(
        r'href="mail-inbox/([A-Za-z0-9_-]+)"',
        r'href="" data-hc-mail-item="\1"',
        html,
    )
    html = _inject_script(
        html,
        r"""
(() => {
  const root = window.location.pathname.replace(/\/+$/, '');
  document.querySelectorAll('[data-hc-mail-action="refresh"]').forEach((form) => {
    form.action = root + '/refresh';
  });
  document.querySelectorAll('[data-hc-mail-item]').forEach((link) => {
    link.href = root + '/' + encodeURIComponent(link.dataset.hcMailItem || '');
  });
})();
""",
    )
    return _html_response(response, html)


def _fix_detail_page(response: Any) -> Any:
    if not isinstance(response, HTMLResponse):
        return response
    html = response.body.decode(response.charset or "utf-8", errors="replace")
    html = html.replace(
        'action="assign"',
        'action="" data-hc-mail-suffix="/assign"',
    )
    html = html.replace(
        'action="ignore"',
        'action="" data-hc-mail-suffix="/ignore"',
    )
    html = html.replace(
        'href="../mail-inbox"',
        'href="" data-hc-mail-back="1"',
    )
    html = _inject_script(
        html,
        r"""
(() => {
  const current = window.location.pathname.replace(/\/+$/, '');
  const inbox = current.replace(/\/[^/]+$/, '');
  document.querySelectorAll('[data-hc-mail-suffix]').forEach((form) => {
    form.action = current + (form.dataset.hcMailSuffix || '');
  });
  document.querySelectorAll('[data-hc-mail-back]').forEach((link) => {
    link.href = inbox;
  });
})();
""",
    )
    return _html_response(response, html)


def register_mail_inbox_route_fix(app: FastAPI) -> None:
    if getattr(app.state, "mail_inbox_route_fix_registered", False):
        return

    inbox_endpoint = _take_route(app, "/mail-inbox", "GET")
    detail_endpoint = _take_route(app, "/mail-inbox/{item_id}", "GET")
    if inbox_endpoint is None or detail_endpoint is None:
        return

    @app.get("/mail-inbox", response_class=HTMLResponse)
    async def mail_inbox_fixed(message: str | None = None) -> Any:
        return _fix_inbox_page(await _call(inbox_endpoint, message=message))

    @app.get("/mail-inbox/{item_id}", response_class=HTMLResponse)
    async def mail_inbox_detail_fixed(item_id: str) -> Any:
        return _fix_detail_page(await _call(detail_endpoint, item_id=item_id))

    app.state.mail_inbox_route_fix_registered = True
