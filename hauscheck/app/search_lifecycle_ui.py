from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

import app.focused_ui as focused_ui
from app.main import criteria_summary, layout, money, num, reasons_from_json, title_from_listing_url
from app.search_lifecycle import (
    delete_search_profile_full,
    ensure_search_lifecycle_schema,
    list_candidate_events,
    list_candidate_price_history,
)
from app.storage import connect, get_search_profile, list_search_profiles, row_to_dict
from app.ui_helpers import candidate_score_html, esc, format_datetime


LIFECYCLE_CSS = focused_ui.FOCUS_CSS + """
<style>
  .status-line { display:flex; flex-wrap:wrap; gap:5px; margin:7px 0; }
  .price-change { padding:9px 11px; border-radius:11px; background:#1f3c2c; color:#d8ffe7; margin:8px 0; }
  .price-change.up { background:#55372b; color:#ffe0d3; }
  .lifecycle-note { padding:9px 11px; border-left:4px solid #2f80ed; background:#132334; border-radius:8px; margin:8px 0; }
  .offline-note { border-left-color:#8f969d; background:#20262b; }
  .profile-head { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }
  .profile-head h3 { margin:0; }
  .profile-actions { display:flex; gap:7px; flex-wrap:wrap; }
  .profile-actions form { margin:0; }
  .profile-delete { background:#5b2a2a !important; }
  .history-list { margin:8px 0 0; padding-left:20px; }
  .history-list li { margin:4px 0; }
  @media (max-width:680px) {
    .profile-head { display:block; }
    .profile-actions { margin-top:8px; }
    .profile-actions .button, .profile-actions button { width:100%; }
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


def _candidate_rows(statuses: tuple[str, ...]) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in statuses)
    with connect() as con:
        rows = con.execute(
            f"""
            SELECT c.*, p.name AS profile_name
            FROM search_candidates c
            LEFT JOIN search_profiles p ON p.id = c.profile_id
            WHERE c.status IN ({placeholders})
            ORDER BY COALESCE(c.last_changed_at, c.first_seen_at) DESC
            """,
            statuses,
        ).fetchall()
    return [row_to_dict(row) or {} for row in rows]


def _deduplicate(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.get("external_id") or candidate.get("canonical_url") or candidate.get("source_url") or candidate.get("id"))
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def _status_label(status: str) -> tuple[str, str]:
    return {
        "new": ("neu", "good"),
        "review": ("prüfen", "warn"),
        "changed": ("geändert", "warn"),
        "reactivated": ("wieder online", "good"),
        "offline": ("offline", "bad"),
        "filtered": ("gefiltert", "bad"),
        "imported": ("importiert", ""),
    }.get(status, (status, ""))


def _json_list(value: object) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
        return [str(item) for item in parsed] if isinstance(parsed, list) else []
    except Exception:
        return []


def _price_change_html(candidate: dict[str, Any]) -> str:
    previous = candidate.get("previous_price_eur")
    current = candidate.get("price_eur")
    if previous in (None, "") or current in (None, "") or float(previous) == float(current):
        return ""
    try:
        percent = float(candidate.get("price_change_percent") or 0)
    except Exception:
        percent = 0
    direction_class = "up" if percent > 0 else ""
    sign = "+" if percent > 0 else ""
    return f"""
    <div class="price-change {direction_class}">
      <strong>Preisänderung:</strong> {money(previous)} → {money(current)} ({sign}{str(round(percent, 1)).replace('.', ',')} %)<br>
      <span class="muted">{esc(format_datetime(candidate.get('price_changed_at')))}</span>
    </div>
    """


def _history_html(candidate_id: str) -> str:
    prices = list_candidate_price_history(candidate_id, 8)
    events = list_candidate_events(candidate_id, 8)
    if len(prices) <= 1 and not events:
        return ""
    price_items = "".join(
        f"<li>{money(item.get('price_eur'))} · {esc(format_datetime(item.get('observed_at')))}</li>"
        for item in prices
    )
    event_items = "".join(
        f"<li>{esc(item.get('summary'))} · {esc(format_datetime(item.get('created_at')))}</li>"
        for item in events
    )
    return f"""
    <details>
      <summary>Verlauf anzeigen</summary>
      {f'<strong>Preise</strong><ul class="history-list">{price_items}</ul>' if price_items else ''}
      {f'<strong>Änderungen</strong><ul class="history-list">{event_items}</ul>' if event_items else ''}
    </details>
    """


def _candidate_card(candidate: dict[str, Any], *, offline: bool = False) -> str:
    candidate_id = str(candidate.get("id") or "")
    source_url = str(candidate.get("source_url") or "")
    preview = str(candidate.get("preview_image_url") or "").strip()
    image = f'<img src="{esc(preview)}" alt="Vorschaubild">' if preview else '<div class="listing-no-image">Kein Bild</div>'
    status = str(candidate.get("status") or "new")
    status_text, status_class = _status_label(status)
    reasons = reasons_from_json(candidate.get("filter_reasons"))
    changes = _json_list(candidate.get("change_summary"))
    change_html = ""
    if changes:
        change_html = f'<div class="lifecycle-note"><strong>Geändert:</strong> {" · ".join(esc(item) for item in changes)}</div>'
    if status == "reactivated":
        change_html = f'<div class="lifecycle-note"><strong>Wieder online</strong> seit {esc(format_datetime(candidate.get("reactivated_at")))}</div>' + change_html
    if offline:
        change_html = f'<div class="lifecycle-note offline-note"><strong>Offline</strong> seit {esc(format_datetime(candidate.get("offline_at")))}</div>' + change_html

    if offline:
        actions = f"""
        <a class="button secondary" href="{esc(source_url)}" target="_blank">Inserat prüfen</a>
        <form method="post" action="search/candidates/{esc(candidate_id)}/reject" data-no-loading="true"><button class="danger" type="submit">Archivieren</button></form>
        """
    else:
        actions = f"""
        <form method="post" action="../import" data-loading="Inserat wird importiert, Medien werden geladen und die Analyse wird gestartet …">
          <input type="hidden" name="url" value="{esc(source_url)}">
          <input type="hidden" name="preview_image_url" value="{esc(preview)}">
          <button type="submit">Hausakte anlegen</button>
        </form>
        <form method="post" action="search/candidates/{esc(candidate_id)}/reject" data-no-loading="true" onsubmit="return confirm('Diesen Kandidaten ablehnen?');"><button class="danger" type="submit">🗑️ Ablehnen</button></form>
        <a class="button secondary" href="{esc(source_url)}" target="_blank">Inserat öffnen</a>
        """

    return f"""
    <article class="card candidate-card">
      <a href="{esc(source_url)}" target="_blank">{image}</a>
      <div class="candidate-body">
        <h3>{esc(candidate.get('title') or title_from_listing_url(source_url))}</h3>
        <div class="status-line"><span class="pill {status_class}">{esc(status_text)}</span><span class="pill">{esc(candidate.get('profile_name') or 'Suchprofil')}</span></div>
        <p><span class="pill">{money(candidate.get('price_eur'))}</span><span class="pill">{num(candidate.get('living_area_m2'), ' m² Wfl.')}</span><span class="pill">{num(candidate.get('plot_area_m2'), ' m² Grund')}</span><span class="pill">HWB {num(candidate.get('energy_hwb'))}</span></p>
        {_price_change_html(candidate)}
        {change_html}
        {candidate_score_html(candidate, status if status in {'new', 'review'} else 'new')}
        <p class="muted">{' · '.join(esc(reason) for reason in reasons[:4])}</p>
        <p class="muted">Erstmals: {esc(format_datetime(candidate.get('first_seen_at')))} · zuletzt gesehen: {esc(format_datetime(candidate.get('last_seen_at')))}</p>
        {_history_html(candidate_id)}
        <div class="candidate-actions">{actions}</div>
      </div>
    </article>
    """


def _profile_card(profile: dict[str, Any]) -> str:
    pid = str(profile.get("id") or "")
    enabled = bool(int(profile.get("enabled") or 0))
    mode = str(profile.get("automation_mode") or "manual")
    selected = lambda value: "selected" if mode == value else ""
    with connect() as con:
        candidate_count = con.execute("SELECT COUNT(*) FROM search_candidates WHERE profile_id = ?", (pid,)).fetchone()[0]
    return f"""
    <div class="card">
      <div class="profile-head">
        <div><h3>{esc(profile.get('name'))}</h3><p class="muted">{candidate_count} gespeicherte Kandidaten</p></div>
        <div class="profile-actions">
          <form method="post" action="search/profiles/{esc(pid)}/delete" data-no-loading="true" onsubmit="return confirm('Suchprofil inklusive Kandidaten und Preisverlauf wirklich löschen? Bereits angelegte Hausakten bleiben erhalten.');">
            <button class="profile-delete" type="submit" title="Suchprofil löschen">🗑️ Löschen</button>
          </form>
        </div>
      </div>
      <p>{criteria_summary(profile)}</p>
      <p class="muted">Letzter Lauf: {esc(format_datetime(profile.get('last_run_at'), 'noch nie'))}<br>{esc(profile.get('last_run_status') or '')}</p>
      <form method="post" action="search/profiles/{esc(pid)}" data-loading="Suchprofil wird gespeichert …">
        <div class="grid">
          <div><label>Status</label><select name="enabled"><option value="1" {'selected' if enabled else ''}>aktiv</option><option value="0" {'selected' if not enabled else ''}>pausiert</option></select></div>
          <div><label>Modus</label><select name="automation_mode"><option value="manual" {selected('manual')}>nur manuell</option><option value="review" {selected('review')}>automatisch suchen, manuell importieren</option><option value="automatic" {selected('automatic')}>automatisch suchen und importieren</option></select></div>
          <div><label>Intervall Minuten</label><input name="run_interval_minutes" type="number" min="15" max="1440" value="{esc(profile.get('run_interval_minutes') or 60)}"></div>
          <div><label>Max. Treffer</label><input name="max_results" type="number" min="10" max="160" value="{esc(profile.get('max_results') or 80)}"></div>
          <div><label>Auto-Import ab Score</label><input name="auto_import_min_score" type="number" min="0" max="100" value="{esc(profile.get('auto_import_min_score') or 68)}"></div>
          <div><label>Max. Auto-Importe</label><input name="auto_import_limit_per_run" type="number" min="1" max="10" value="{esc(profile.get('auto_import_limit_per_run') or 2)}"></div>
        </div>
        <button type="submit">Speichern</button>
      </form>
    </div>
    """


def _new_profile_form() -> str:
    return """
    <div class="card">
      <h2>Neues Suchprofil</h2>
      <form method="post" action="profiles" data-loading="Suchprofil wird gespeichert …">
        <label>Name</label><input name="name" placeholder="Familienhaus Südweststeiermark" required>
        <label>Regionen / Orte</label><input name="regions" value="Wies, Eibiswald, Oberhaag, Gleinstätten, Bad Schwanberg, Pölfing-Brunn, Frauental, Deutschlandsberg">
        <label>Willhaben PLZ / areaIds</label><input name="area_ids" value="8551,8552,8544,8553">
        <label>Willhaben-Suchergebnis-URL optional</label><input name="search_url">
        <div class="grid">
          <div><label>Zielpreis bis €</label><input name="soft_max_price_eur" type="number" value="380000"></div>
          <div><label>Harte Grenze bis €</label><input name="max_price_eur" type="number" value="400000"></div>
          <div><label>Mindestwohnfläche m²</label><input name="min_living_area_m2" type="number" step="0.1" value="120"></div>
          <div><label>Wunsch-Grundstück m²</label><input name="min_plot_area_m2" type="number" step="0.1" value="700"></div>
          <div><label>HWB Warnung ab</label><input name="hwb_warn" type="number" step="0.1" value="200"></div>
          <div><label>HWB kritisch ab</label><input name="hwb_reject" type="number" step="0.1" value="300"></div>
        </div>
        <label>Ausschluss-/Prüfbegriffe</label><input name="exclude_roads" value="B76,B69,Bundesstraße,Hauptstraße">
        <div class="grid">
          <div><label>Ölheizung</label><select name="oil_policy"><option value="review" selected>prüfen</option><option value="reject">ausschließen</option><option value="allow">zulassen</option></select></div>
          <div><label>Modus</label><select name="automation_mode"><option value="manual">nur manuell</option><option value="review" selected>automatisch suchen, manuell importieren</option><option value="automatic">automatisch suchen und importieren</option></select></div>
          <div><label>Intervall Minuten</label><input name="run_interval_minutes" type="number" value="60" min="15"></div>
          <div><label>Max. Treffer</label><input name="max_results" type="number" value="80" min="10" max="160"></div>
          <div><label>Auto-Import ab Score</label><input name="auto_import_min_score" type="number" value="68" min="0" max="100"></div>
          <div><label>Max. Auto-Importe</label><input name="auto_import_limit_per_run" type="number" value="2" min="1" max="10"></div>
        </div>
        <button type="submit">Suchprofil speichern</button>
      </form>
    </div>
    """


def _patch_house_card() -> None:
    original = focused_ui._house_card
    if getattr(original, "_lifecycle_patched", False):
        return

    def wrapped(house: dict[str, Any], *, rejected: bool = False) -> str:
        html = original(house, rejected=rejected)
        if rejected:
            return html
        house_id = str(house.get("id") or "")
        with connect() as con:
            candidate = con.execute(
                """
                SELECT change_summary, last_changed_at, price_changed_at
                FROM search_candidates
                WHERE imported_house_id = ? AND needs_reanalysis = 1
                ORDER BY COALESCE(last_changed_at, price_changed_at) DESC LIMIT 1
                """,
                (house_id,),
            ).fetchone()
        if not candidate:
            return html
        note = f"""
        <div class="lifecycle-note">
          <strong>Inserat geändert</strong><br>
          Neue Analyse empfohlen · {esc(format_datetime(candidate['last_changed_at'] or candidate['price_changed_at']))}
          <form method="post" action="houses/{esc(house_id)}/analysis/retry" data-loading="Aktualisierte Analyse wird angestoßen …"><button class="secondary" type="submit">Analyse aktualisieren</button></form>
        </div>
        """
        return html.replace('<div class="house-actions">', note + '<div class="house-actions">', 1)

    setattr(wrapped, "_lifecycle_patched", True)
    focused_ui._house_card = wrapped


def register_search_lifecycle_ui(app: FastAPI) -> None:
    ensure_search_lifecycle_schema()
    _patch_house_card()
    _remove_route(app, "/search", "GET")
    _remove_route(app, "/settings/search", "GET")

    @app.get("/search", response_class=HTMLResponse)
    def lifecycle_search() -> HTMLResponse:
        open_candidates = _deduplicate(_candidate_rows(("changed", "reactivated", "new", "review")))
        offline_candidates = _deduplicate(_candidate_rows(("offline",)))
        body = f"""
        {LIFECYCLE_CSS}
        <nav class="app-toolbar">
          <a class="icon-button" href="./" title="Hausakten" aria-label="Hausakten">🏠</a>
          <form method="post" action="search/run-all" data-loading="Willhaben wird durchsucht …"><button class="icon-button primary" type="submit" title="Suche erneut starten" aria-label="Suche erneut starten">🔍</button></form>
          <a class="icon-button" href="settings/search" title="Suchprofile einstellen" aria-label="Suchprofile einstellen">⚙️</a>
        </nav>
        <div class="card">
          <h2>Suchergebnisse</h2>
          <p><span class="pill good">{len(open_candidates)} offen</span><span class="pill bad">{len(offline_candidates)} offline</span></p>
          <p class="muted">Preisänderungen, wieder aktive Inserate und sonstige relevante Änderungen werden hervorgehoben.</p>
        </div>
        <div class="listing-stack">{''.join(_candidate_card(candidate) for candidate in open_candidates) if open_candidates else '<div class="card empty-state"><h3>Keine offenen Kandidaten</h3><p class="muted">Starte die Suche über die Lupe.</p></div>'}</div>
        <details class="card" {'open' if offline_candidates else ''}>
          <summary><strong>Offline-Inserate ({len(offline_candidates)})</strong></summary>
          <p class="muted">Ein Inserat gilt erst nach zwei erfolgreichen Suchläufen ohne Fund als offline.</p>
          <div class="listing-stack">{''.join(_candidate_card(candidate, offline=True) for candidate in offline_candidates) if offline_candidates else '<p class="muted">Keine Offline-Inserate.</p>'}</div>
        </details>
        """
        return layout("Suche", body, home_href="../")

    @app.get("/settings/search", response_class=HTMLResponse)
    def lifecycle_search_settings() -> HTMLResponse:
        profiles = list_search_profiles()
        body = f"""
        {LIFECYCLE_CSS}
        <nav class="app-toolbar">
          <a class="icon-button" href="../" title="Einstellungen" aria-label="Einstellungen">←</a>
          <a class="icon-button primary" href="search/new" title="Neues Suchprofil" aria-label="Neues Suchprofil">＋</a>
          <a class="icon-button" href="../../search" title="Suchergebnisse" aria-label="Suchergebnisse">🔍</a>
        </nav>
        <h2>Suchprofile</h2>
        <div class="settings-list">{''.join(_profile_card(profile) for profile in profiles) if profiles else '<div class="card empty-state"><h3>Noch kein Suchprofil</h3><p class="muted">Lege es oben über ＋ an.</p></div>'}</div>
        """
        return layout("Suchprofile", body, home_href="../../")

    @app.get("/settings/search/new", response_class=HTMLResponse)
    def new_search_profile() -> HTMLResponse:
        body = f"""
        {LIFECYCLE_CSS}
        <nav class="app-toolbar"><a class="icon-button" href="../search" title="Zurück" aria-label="Zurück">←</a></nav>
        {_new_profile_form()}
        """
        return layout("Neues Suchprofil", body, home_href="../../../")

    @app.post("/settings/search/profiles/{profile_id}/delete")
    async def delete_profile(profile_id: str) -> RedirectResponse:
        if not get_search_profile(profile_id):
            raise HTTPException(status_code=404, detail="Suchprofil nicht gefunden")
        try:
            delete_search_profile_full(profile_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return RedirectResponse("../../../search", status_code=303)
