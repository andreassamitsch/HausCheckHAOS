from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.main import layout, money, num
from app.pipeline_status import get_pipeline_status, pipeline_counts
from app.product_ui import PRODUCT_CSS, _candidate_totals, _pipeline_badge
from app.search_automation import search_automation_enabled
from app.storage import list_houses, list_media, list_search_profiles
from app.ui_helpers import esc


def _methods(route: Any) -> set[str]:
    return set(getattr(route, "methods", set()) or set())


def register_dashboard_automation_ui(app: FastAPI) -> None:
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (getattr(route, "path", "") == "/" and "GET" in _methods(route))
    ]

    @app.get("/", response_class=HTMLResponse)
    def dashboard_automatic() -> HTMLResponse:
        houses = list_houses()
        profiles = list_search_profiles()
        pcounts = pipeline_counts()
        ccounts = _candidate_totals()
        active_profiles = [
            profile
            for profile in profiles
            if bool(int(profile.get("enabled") or 0))
            and str(profile.get("automation_mode") or "manual") in {"review", "automatic"}
        ]
        full_auto_profiles = [
            profile for profile in active_profiles if str(profile.get("automation_mode") or "") == "automatic"
        ]

        cards: list[str] = []
        for house in houses:
            hid = str(house.get("id") or "")
            status = get_pipeline_status(hid)
            local_images = [
                item
                for item in list_media(hid)
                if item.get("kind") == "image" and item.get("download_status") == "downloaded"
            ]
            if local_images:
                image = f'<img class="thumb" src="media/{esc(local_images[-1].get("id"))}" alt="Bild">'
            elif house.get("preview_image_url"):
                image = f'<img class="thumb" src="{esc(house.get("preview_image_url"))}" alt="Vorschaubild">'
            else:
                image = '<div class="muted">Noch kein Bild</div>'
            cards.append(
                f"""
                <div class="card">
                  {image}
                  <h3>{esc(house.get('title'))}</h3>
                  <div class="muted">{esc(house.get('location_text') or 'Lage unbekannt')}</div>
                  <p><span class="pill">{money(house.get('price_eur'))}</span><span class="pill">{num(house.get('living_area_m2'), ' m² Wfl.')}</span><span class="pill">{num(house.get('plot_area_m2'), ' m² Grund')}</span></p>
                  <p>{_pipeline_badge(status)}</p>
                  <a class="button" href="houses/{esc(hid)}">Hausakte öffnen</a>
                </div>
                """
            )

        scheduler_active = search_automation_enabled()
        body = f"""
        {PRODUCT_CSS}
        <div class="grid">
          <div class="card">
            <h2>Objekt hinzufügen</h2>
            <p class="muted">Direktlink importieren oder automatisch über Willhaben suchen.</p>
            <div class="top-actions"><a class="button" href="import">Inserat importieren</a><a class="button secondary" href="search">Automatische Suche</a></div>
          </div>
          <div class="card">
            <h2>Analyse-Pipeline</h2>
            <div class="dashboard-metrics"><span class="pill">{len(houses)} Hausakten</span><span class="pill warn">{pcounts['waiting']} warten</span><span class="pill good">{pcounts['completed']} abgeschlossen</span><span class="pill bad">{pcounts['errors']} Fehler</span></div>
            <p class="muted">Medien, GitHub-Artifact, ChatGPT-Auswertung und Rückimport laufen automatisch.</p>
          </div>
          <div class="card">
            <h2>Willhaben-Automatik</h2>
            <div class="dashboard-metrics"><span class="pill {'good' if scheduler_active else 'bad'}">Scheduler {'aktiv' if scheduler_active else 'deaktiviert'}</span><span class="pill">{len(active_profiles)} aktive Profile</span><span class="pill good">{len(full_auto_profiles)} mit Auto-Import</span><span class="pill good">{ccounts['new']} neue Kandidaten</span><span class="pill warn">{ccounts['review']} zu prüfen</span></div>
            <p class="muted">Passende Treffer können automatisch als Hausakte angelegt und zur Bildanalyse geschickt werden.</p>
          </div>
        </div>
        <h2>Hausakten</h2>
        <div class="grid">{''.join(cards) if cards else '<div class="card muted">Noch keine Objekte vorhanden.</div>'}</div>
        """
        return layout("HausCheck", body, home_href="./")
