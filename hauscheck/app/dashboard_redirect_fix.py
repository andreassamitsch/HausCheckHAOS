from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from starlette.datastructures import QueryParams

import app.mobile_first_ui as mobile_first_ui
import app.mobile_layout_state_fix as layout_state
import app.modern_ui as modern_ui
from app.storage import list_houses


def _methods(route: Any) -> set[str]:
    return set(getattr(route, "methods", set()) or set())


def _remove_route(app: FastAPI, path: str, method: str) -> None:
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (getattr(route, "path", "") == path and method in _methods(route))
    ]


def register_dashboard_redirect_fix(app: FastAPI) -> None:
    _remove_route(app, "/", "GET")

    @app.get("/", response_class=HTMLResponse)
    def dashboard_without_redirect_loop(request: Request) -> Response:
        raw_query = str(request.url.query or "").strip()
        saved_query = str(request.cookies.get(layout_state._COOKIE_NAME) or "").strip().lstrip("?")
        effective_query = raw_query or saved_query

        # _dashboard_state benötigt lediglich query_params. Ein Redirect ist für die
        # Wiederherstellung der Filter nicht nötig und verursacht unter HA-Ingress
        # je nach Query-Weitergabe eine Endlosschleife.
        state_request = SimpleNamespace(query_params=QueryParams(effective_query))
        sort, q, min_score, max_price, max_hwb, normalized_query = layout_state._dashboard_state(state_request)

        houses = [
            house
            for house in list_houses()
            if str(house.get("status") or "new") != "rejected"
        ]
        filtered = mobile_first_ui._filter_and_sort(
            houses,
            sort,
            q,
            min_score,
            max_price,
            max_hwb,
        )
        candidate_count = modern_ui._candidate_count()
        candidate_link = (
            f'<a class="candidate-mini" href="search">{modern_ui.icon("search")}<strong>{candidate_count}</strong> nicht importierte Kandidaten anzeigen</a>'
            if candidate_count
            else ""
        )
        body = f"""
        <div class="page-heading">
          <div><h1>Hausakten</h1><p>{len(houses)} aktive Objekte</p></div>
          <div class="page-actions"><a class="button secondary" href="search">{modern_ui.icon('search')} Suche</a><a class="button" href="import">{modern_ui.icon('plus')} Inserat</a></div>
        </div>
        {candidate_link}
        {layout_state._filter_panel_with_reset(sort, q, min_score, max_price, max_hwb)}
        <p class="muted results-note">{len(filtered)} von {len(houses)} Hausakten angezeigt</p>
        <div class="house-grid">{''.join(mobile_first_ui._house_card(house) for house in filtered) if filtered else '<div class="card empty-state"><h2>Keine passenden Hausakten</h2><p class="muted">Filter zurücksetzen oder Suche anpassen.</p></div>'}</div>
        """
        response = modern_ui.modern_layout("Hausakten", body, home_href="./")
        response.set_cookie(
            layout_state._COOKIE_NAME,
            normalized_query,
            max_age=31536000,
            path="/",
            samesite="lax",
            httponly=False,
        )
        return response
