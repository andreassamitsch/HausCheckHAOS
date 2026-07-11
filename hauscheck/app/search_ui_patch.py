from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from app.main import (
    criteria_summary,
    esc,
    layout,
    money,
    num,
    reasons_from_json,
    resolve_search_urls,
    source_url_exists,
    status_pill,
    title_from_listing_url,
    visible_candidates,
)
from app.storage import get_search_profile, list_search_candidates
from app.ui_helpers import candidate_score_html


def _methods(route: Any) -> set[str]:
    return set(getattr(route, "methods", set()) or set())


def _safe_candidate_score(candidate: dict[str, Any], status: str) -> str:
    try:
        return candidate_score_html(candidate, status)
    except Exception:
        return ""


def register_search_profile_patch(app: FastAPI) -> None:
    # Alte Route aus app.main entfernen. Dadurch wird diese robuste Route verwendet.
    app.router.routes = [
        route
        for route in app.router.routes
        if not (getattr(route, "path", "") == "/search/profiles/{profile_id}" and "GET" in _methods(route))
    ]

    @app.get("/search/profiles/{profile_id}", response_class=HTMLResponse)
    def profile_detail_safe(profile_id: str) -> HTMLResponse:
        profile = get_search_profile(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Suchprofil nicht gefunden")

        try:
            raw_candidates = list_search_candidates(profile_id)
            candidates = visible_candidates(raw_candidates)
        except Exception:
            candidates = []

        cards: list[str] = []
        for cand in candidates:
            try:
                source_url = str(cand.get("source_url") or "")
                imported = cand.get("status") == "imported" or source_url_exists(source_url)
                status = "imported" if imported else str(cand.get("status") or "new")
                reasons = reasons_from_json(cand.get("filter_reasons"))
                reason_html = "<br>".join(esc(reason) for reason in reasons[:4])
                preview = str(cand.get("preview_image_url") or "").strip()
                if preview:
                    preview_html = f'<a class="listing-image" href="{esc(source_url)}" target="_blank"><img src="{esc(preview)}" alt="Vorschaubild"></a>'
                else:
                    preview_html = f'<a class="listing-image" href="{esc(source_url)}" target="_blank"><div class="listing-no-image">kein Bild</div></a>'

                action = ""
                if not imported and status != "filtered":
                    action = f"""
                    <form method="post" action="../../import" data-loading="Inserat wird importiert und Bilder werden geladen …">
                      <input type="hidden" name="url" value="{esc(source_url)}">
                      <input type="hidden" name="preview_image_url" value="{esc(preview)}">
                      <button type="submit">Importieren</button>
                    </form>
                    """
                elif status == "filtered":
                    action = "<span class='muted'>ausgefiltert</span>"

                title = cand.get("title") or title_from_listing_url(source_url)
                cards.append(
                    f"""
                    <article class="listing-card">
                      {preview_html}
                      <div class="listing-body">
                        <a class="listing-title" href="{esc(source_url)}" target="_blank">{esc(title)}</a>
                        <div>{status_pill(status)}</div>
                        {_safe_candidate_score(cand, status)}
                        <div class="listing-facts">
                          <span class="pill">{money(cand.get('price_eur'))}</span>
                          <span class="pill">{num(cand.get('living_area_m2'), ' m² Wfl.')}</span>
                          <span class="pill">{num(cand.get('plot_area_m2'), ' m² Grund')}</span>
                          <span class="pill">HWB {num(cand.get('energy_hwb'))}</span>
                        </div>
                        <div class="listing-reasons">{reason_html}</div>
                        <div class="listing-actions">
                          {action}
                          <a class="button secondary" href="{esc(source_url)}" target="_blank">Bei Willhaben öffnen</a>
                        </div>
                      </div>
                    </article>
                    """
                )
            except Exception as exc:
                cards.append(f"<div class='card muted'>Kandidat konnte nicht angezeigt werden: {esc(str(exc)[:200])}</div>")

        try:
            source_links = "<br>".join(
                f'<a href="{esc(url)}" target="_blank">Willhaben-Suchquelle {idx}</a>'
                for idx, url in enumerate(resolve_search_urls(profile), start=1)
            )
        except Exception:
            source_links = ""

        body = f"""
        <div class="card">
          <h2>{esc(profile.get('name'))}</h2>
          <p>{criteria_summary(profile)}</p>
          <p class="muted source-links">{source_links}</p>
          <p><span class="pill">{len(candidates)} Kandidaten sichtbar</span><span class="pill">Letzter Lauf: {esc(profile.get('last_run_at') or 'noch nie')}</span></p>
          <form method="post" action="{profile_id}/run" data-loading="Suchprofil wird gestartet. Kandidaten werden gesucht und geprüft …" style="display:inline"><button type="submit">Suchprofil jetzt starten</button></form>
          <a class="button secondary" href="../../search">Zurück</a>
        </div>
        <section class="listing-stack">{''.join(cards) if cards else '<div class="card muted">Noch keine Kandidaten. Starte das Suchprofil.</div>'}</section>
        """
        return layout("Suchprofil", body, home_href="../../../")
