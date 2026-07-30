from __future__ import annotations

import inspect
import os
from typing import Any, Callable

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

import app.modern_ui as modern_ui
from app.ui_helpers import esc


SUPERVISOR_BASE_URL = "http://supervisor"


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


def _settings_card() -> str:
    return """
    <div class="card section">
      <h2>HausCheck-Updates</h2>
      <p class="muted">Lädt den Home-Assistant-App-Store sofort neu. Damit werden neue HausCheck-Versionen sichtbar, ohne auf den zeitgesteuerten Repository-Check zu warten.</p>
      <form method="post" action="" data-hc-store-reload="1" data-loading="Home-Assistant-App-Store wird neu geladen …">
        <button type="submit">Updates jetzt neu laden</button>
      </form>
    </div>
    <script>
    (() => {
      const settingsPath = window.location.pathname.replace(/\/+$/, '');
      const root = settingsPath.replace(/\/settings$/, '');
      document.querySelectorAll('[data-hc-store-reload]').forEach((form) => {
        form.action = root + '/system/reload-store';
      });
    })();
    </script>
    """


def _inject_settings_card(response: Any) -> Any:
    if not isinstance(response, HTMLResponse):
        return response
    html = response.body.decode(response.charset or "utf-8", errors="replace")
    card = _settings_card()
    html = html.replace("</main>", card + "</main>", 1) if "</main>" in html else html + card
    return _html_response(response, html)


async def reload_supervisor_store() -> dict[str, Any]:
    token = str(os.environ.get("SUPERVISOR_TOKEN") or "").strip()
    if not token:
        raise HTTPException(status_code=503, detail="Supervisor-Zugriff ist nicht verfügbar")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(base_url=SUPERVISOR_BASE_URL, timeout=45.0) as client:
        response = await client.post("/store/reload", headers=headers)
    if response.status_code >= 400:
        detail = response.text.strip()[:800] or f"HTTP {response.status_code}"
        raise HTTPException(status_code=502, detail=f"App-Store konnte nicht neu geladen werden: {detail}")
    try:
        payload = response.json()
    except Exception:
        payload = {"result": response.text.strip() or "ok"}
    return {"ok": True, "supervisor": payload}


def register_supervisor_update_refresh(app: FastAPI) -> None:
    if getattr(app.state, "supervisor_update_refresh_registered", False):
        return

    settings_endpoint = _take_route(app, "/settings", "GET")
    if settings_endpoint is not None:
        @app.get("/settings", response_class=HTMLResponse)
        async def settings_with_update_refresh() -> Any:
            return _inject_settings_card(await _call(settings_endpoint))

    @app.post("/system/reload-store", response_class=HTMLResponse)
    async def reload_store_route() -> HTMLResponse:
        result = await reload_supervisor_store()
        body = f"""
        <div class="page-heading">
          <div><h1>Updates neu geladen</h1><p>Home Assistant hat den App-Store und die Add-on-Repositories neu eingelesen.</p></div>
        </div>
        <div class="card notice"><strong>Erfolgreich.</strong> Öffne jetzt die HausCheck-Add-on-Seite; eine neu veröffentlichte Version sollte dort angezeigt werden.</div>
        <div class="section"><a class="button" href="../settings">Zurück zu Einstellungen</a></div>
        <details class="section"><summary>Technische Antwort</summary><pre style="white-space:pre-wrap">{esc(result)}</pre></details>
        """
        return modern_ui.modern_layout("Updates neu geladen", body, home_href="../")

    app.state.supervisor_update_refresh_registered = True
