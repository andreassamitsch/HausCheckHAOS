from __future__ import annotations

from urllib.parse import urlencode
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

import app.mobile_first_ui as mobile_first_ui
import app.modern_ui as modern_ui
from app.storage import list_houses


_PATCH_MARKER = "hc-mobile-layout-state-fix-v1"
_COOKIE_NAME = "hc_dashboard_filters"
_ALLOWED_SORTS = {
    "created_desc",
    "created_asc",
    "score_desc",
    "score_asc",
    "location_asc",
    "price_asc",
    "price_desc",
    "hwb_asc",
    "living_desc",
    "plot_desc",
}

MOBILE_LAYOUT_CSS = r"""
<style id="hc-mobile-layout-state-fix-v1">
/* Harte Begrenzung auf die tatsächliche Ingress-Breite. */
html,
body {
  width:100%;
  min-width:0;
  max-width:100%;
  overflow-x:hidden!important;
  overscroll-behavior-x:none;
}
.app-header,
.app-header-inner,
.app-main,
.app-main>* {
  width:100%;
  min-width:0!important;
  max-width:100%!important;
}
.app-main {
  overflow-x:hidden!important;
}

/* Jede Layout-Spalte darf auf Smartphonebreite tatsächlich schrumpfen. */
.two-column,
.two-column>*,
.grid,
.grid>*,
.house-grid,
.house-grid>*,
.section,
.section>*,
.card,
.card>*,
.card form,
.card details,
.card summary,
.facts-grid,
.facts-grid>*,
.action-row,
.page-heading,
.page-heading>*,
.detail-toolbar,
.detail-toolbar>*,
.source-card,
.notice,
.object-heading,
.analysis-card,
.analysis-grid,
.valuation-grid,
.valuation-card,
.investment-grid,
.investment-card {
  min-width:0!important;
  max-width:100%!important;
}

/* Fließtext und KI-Begründungen dürfen nie rechts abgeschnitten werden. */
.card p,
.card li,
.card h1,
.card h2,
.card h3,
.card h4,
.card summary,
.card .muted,
.card .subtle,
.analysis-card,
.valuation-card,
.investment-card,
.object-heading h1,
.source-card,
.notice {
  white-space:normal!important;
  overflow-wrap:anywhere!important;
  word-break:break-word!important;
  text-overflow:clip!important;
  overflow:visible;
}
.card h2 {
  font-size:clamp(21px,6vw,28px);
  line-height:1.16;
}
.card pre,
.card code {
  max-width:100%;
  white-space:pre-wrap;
  overflow-wrap:anywhere;
  word-break:break-word;
}
.pill {
  min-width:0;
  max-width:100%;
}

/* Aktionen statt horizontalem Abschneiden als gut treffbare 2x2-Matrix. */
@media (max-width:820px) {
  .detail-toolbar {
    position:static!important;
    display:grid!important;
    grid-template-columns:repeat(2,minmax(0,1fr));
    gap:8px;
    margin:10px 0 16px!important;
    padding:8px!important;
    overflow:visible!important;
  }
  .detail-toolbar form,
  .detail-toolbar a,
  .detail-toolbar button {
    width:100%!important;
    min-width:0!important;
    max-width:100%!important;
    margin:0!important;
  }
  .detail-toolbar .button,
  .detail-toolbar button {
    min-height:46px;
    padding:9px 8px;
    white-space:normal!important;
    line-height:1.18;
    font-size:14px;
  }
  .detail-toolbar svg {
    width:18px;
    height:18px;
    flex:0 0 18px;
  }
  .two-column {
    display:grid!important;
    grid-template-columns:minmax(0,1fr)!important;
  }
}

@media (max-width:420px) {
  .app-main {
    padding-left:10px!important;
    padding-right:10px!important;
  }
  .card {
    padding:12px!important;
    border-radius:14px!important;
  }
  .detail-toolbar {
    gap:6px;
    padding:6px!important;
  }
  .detail-toolbar .button,
  .detail-toolbar button {
    font-size:13px;
    padding:8px 6px;
  }
  .bottom-nav {
    left:7px!important;
    right:7px!important;
  }
}
</style>
"""


def _methods(route: Any) -> set[str]:
    return set(getattr(route, "methods", set()) or set())


def _remove_route(app: FastAPI, path: str, method: str) -> None:
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (getattr(route, "path", "") == path and method in _methods(route))
    ]


def _clean_int(value: str | None) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(float(text.replace(",", ".")))
    except Exception:
        return None


def _clean_float(value: str | None) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text.replace(",", "."))
    except Exception:
        return None


def _dashboard_state(request: Request) -> tuple[str, str, int | None, int | None, float | None, str]:
    params = request.query_params
    sort = str(params.get("sort") or "created_desc")
    if sort not in _ALLOWED_SORTS:
        sort = "created_desc"
    q = str(params.get("q") or "").strip()
    min_score = _clean_int(params.get("min_score"))
    max_price = _clean_int(params.get("max_price"))
    max_hwb = _clean_float(params.get("max_hwb"))

    normalized: dict[str, str] = {"sort": sort}
    if q:
        normalized["q"] = q
    if min_score is not None:
        normalized["min_score"] = str(max(0, min(min_score, 100)))
        min_score = max(0, min(min_score, 100))
    if max_price is not None:
        normalized["max_price"] = str(max(0, max_price))
        max_price = max(0, max_price)
    if max_hwb is not None:
        normalized["max_hwb"] = str(max(0.0, max_hwb))
        max_hwb = max(0.0, max_hwb)
    return sort, q, min_score, max_price, max_hwb, urlencode(normalized)


def _filter_panel_with_reset(
    sort: str,
    q: str,
    min_score: int | None,
    max_price: int | None,
    max_hwb: float | None,
) -> str:
    panel = mobile_first_ui._filter_panel(sort, q, min_score, max_price, max_hwb)
    return panel.replace('href="./">Zurücksetzen', 'href="dashboard/reset">Zurücksetzen')


def register_mobile_layout_state_fix(app: FastAPI) -> None:
    if _PATCH_MARKER not in modern_ui.MODERN_CSS:
        modern_ui.MODERN_CSS += MOBILE_LAYOUT_CSS

    _remove_route(app, "/", "GET")

    @app.get("/", response_class=HTMLResponse)
    def persistent_mobile_dashboard(request: Request) -> Response:
        raw_query = str(request.url.query or "").strip()
        saved_query = str(request.cookies.get(_COOKIE_NAME) or "").strip().lstrip("?")
        if not raw_query and saved_query:
            return RedirectResponse(f"./?{saved_query}", status_code=307)

        sort, q, min_score, max_price, max_hwb, normalized_query = _dashboard_state(request)
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
        {_filter_panel_with_reset(sort, q, min_score, max_price, max_hwb)}
        <p class="muted results-note">{len(filtered)} von {len(houses)} Hausakten angezeigt</p>
        <div class="house-grid">{''.join(mobile_first_ui._house_card(house) for house in filtered) if filtered else '<div class="card empty-state"><h2>Keine passenden Hausakten</h2><p class="muted">Filter zurücksetzen oder Suche anpassen.</p></div>'}</div>
        """
        response = modern_ui.modern_layout("Hausakten", body, home_href="./")
        response.set_cookie(
            _COOKIE_NAME,
            normalized_query,
            max_age=31536000,
            path="/",
            samesite="lax",
            httponly=False,
        )
        return response

    @app.get("/dashboard/reset")
    def reset_dashboard_filters() -> RedirectResponse:
        response = RedirectResponse("../", status_code=303)
        response.delete_cookie(_COOKIE_NAME, path="/")
        return response
