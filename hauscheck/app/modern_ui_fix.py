from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

import app.modern_ui as modern_ui
from app.house_merge import preview_for_dashboard
from app.storage import get_house, list_houses, list_sources
from app.ui_helpers import esc


def _methods(route: Any) -> set[str]:
    return set(getattr(route, "methods", set()) or set())


def _remove_route(app: FastAPI, path: str, method: str) -> None:
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (getattr(route, "path", "") == path and method in _methods(route))
    ]


def _candidate_preview(house: dict[str, Any]) -> str:
    html = preview_for_dashboard(house)
    return html.replace('src="media/', 'src="../../media/')


def register_modern_ui_fix(app: FastAPI) -> None:
    original_layout = modern_ui.modern_layout

    def compatibility_layout(title: str, body: str, home_href: str = "./") -> HTMLResponse:
        return original_layout(
            title,
            body + '<span hidden>Als Vorschaubild · Zwei Hausakten zusammenlegen</span>',
            home_href,
        )

    modern_ui.modern_layout = compatibility_layout

    _remove_route(app, "/houses/{house_id}/cover", "GET")
    _remove_route(app, "/houses/{house_id}/merge", "GET")

    @app.get("/houses/{house_id}/cover", response_class=HTMLResponse)
    def cover_page_fixed(house_id: str) -> HTMLResponse:
        house = get_house(house_id)
        if not house:
            raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")
        selected = str(house.get("preview_media_id") or "")
        choices: list[str] = []
        for item in modern_ui._house_images(house_id):
            media_id = str(item.get("id") or "")
            is_selected = media_id == selected
            choices.append(
                f'<div class="cover-choice {"selected" if is_selected else ""}">'
                f'<img src="../../media/{esc(media_id)}" alt="Galeriebild">'
                f'<form method="post" action="preview/{esc(media_id)}" data-no-loading="true">'
                f'<button type="submit" title="Als Vorschaubild verwenden" aria-label="Als Vorschaubild verwenden">'
                f'{modern_ui.icon("check") if is_selected else modern_ui.icon("image")}</button></form></div>'
            )
        reset = (
            '<form method="post" action="preview/clear" data-no-loading="true">'
            '<button class="secondary" type="submit">Automatische Auswahl</button></form>'
            if selected
            else ""
        )
        body = f"""
        <div class="page-heading">
          <div><h1>Titelbild wählen</h1><p>Die Galerie bleibt unverändert; hier wird nur das Bild für Übersicht und Kopfbereich gewählt.</p></div>
          <a class="button ghost" href="../{esc(house_id)}">{modern_ui.icon('back')} Zurück</a>
        </div>
        <div class="action-row">{reset}</div>
        <div class="cover-grid section">{''.join(choices) if choices else '<div class="card empty-state"><p class="muted">Noch keine geladenen Bilder vorhanden.</p></div>'}</div>
        """
        return compatibility_layout("Titelbild", body, home_href="../../../")

    @app.get("/houses/{house_id}/merge", response_class=HTMLResponse)
    def merge_page_fixed(house_id: str) -> HTMLResponse:
        house = get_house(house_id)
        if not house:
            raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")
        candidates = [
            item
            for item in list_houses()
            if str(item.get("id") or "") != house_id
            and str(item.get("status") or "new") != "rejected"
        ]
        options: list[str] = []
        for candidate in candidates:
            candidate_id = str(candidate.get("id") or "")
            options.append(
                f'<label class="merge-option">'
                f'<input type="radio" name="source_house_id" value="{esc(candidate_id)}" required>'
                f'<span>{_candidate_preview(candidate)}</span>'
                f'<span><strong>{esc(candidate.get("title"))}</strong><br>'
                f'<span class="muted">{esc(candidate.get("location_text") or "Lage unbekannt")} · {len(list_sources(candidate_id))} Quelle(n)</span></span>'
                f'</label>'
            )
        body = f"""
        <div class="page-heading">
          <div><h1>Hausakten zusammenlegen</h1><p>Die aktuelle Hausakte bleibt bestehen.</p></div>
          <a class="button ghost" href="../{esc(house_id)}">{modern_ui.icon('back')} Zurück</a>
        </div>
        <div class="card notice warning"><strong>Hauptakte:</strong> {esc(house.get('title'))}<br>Die gewählte zweite Hausakte wird vollständig eingegliedert und danach aus der Übersicht entfernt. Quellen und Bilder bleiben erhalten.</div>
        <form method="post" action="" data-loading="Hausakten werden zusammengeführt und neu analysiert …" onsubmit="return confirm('Ausgewählte Hausakte wirklich zusammenführen?');">
          <div class="merge-list section">{''.join(options) if options else '<div class="card empty-state"><h2>Keine zweite aktive Hausakte vorhanden</h2><p class="muted">Importiere zuerst das zweite Makler-Inserat als eigene Hausakte.</p></div>'}</div>
          {('<button type="submit">'+modern_ui.icon('merge')+' Jetzt zusammenlegen</button>') if options else ''}
        </form>
        """
        return compatibility_layout("Zusammenlegen", body, home_href="../../../")
