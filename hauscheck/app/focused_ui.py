from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

import app.search_automation as search_automation
from app.house_manage import delete_house_full
from app.main import (
    build_willhaben_auto_urls,
    criteria_summary,
    layout,
    money,
    num,
    reasons_from_json,
    title_from_listing_url,
)
from app.pipeline_status import get_pipeline_status
from app.product_ui import PRODUCT_CSS, _pipeline_badge
from app.search_automation import execute_profile_cycle, update_profile_automation
from app.storage import (
    connect,
    create_search_profile,
    ensure_columns,
    get_house,
    get_search_candidate,
    get_search_profile,
    list_houses,
    list_media,
    list_search_profiles,
    now_iso,
    row_to_dict,
)
from app.ui_helpers import candidate_score_html, esc, format_datetime, house_score_result


FOCUS_CSS = PRODUCT_CSS + """
<style>
  .app-toolbar { display:flex; justify-content:flex-end; align-items:center; gap:8px; margin-bottom:12px; }
  .app-toolbar form { margin:0; }
  .icon-button { width:44px !important; height:44px; min-width:44px; padding:0 !important; margin:0 !important; border-radius:50% !important; display:inline-grid !important; place-items:center; font-size:20px !important; line-height:1; background:#263746 !important; color:#eef2f4 !important; text-decoration:none; border:1px solid #3a4b59 !important; }
  .icon-button.primary { background:#2f80ed !important; border-color:#2f80ed !important; }
  .icon-button.danger { background:#5b2a2a !important; border-color:#7a3737 !important; color:#ffd7d7 !important; }
  .toolbar-count { position:relative; }
  .toolbar-count span { position:absolute; right:-3px; top:-5px; min-width:18px; height:18px; border-radius:999px; padding:1px 5px; background:#b44343; color:#fff; font-size:11px; display:grid; place-items:center; }
  .house-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(270px,1fr)); gap:12px; }
  .house-card { position:relative; overflow:hidden; padding:0; }
  .house-card-body { padding:13px; }
  .house-card h3 { margin:0 50px 4px 0; line-height:1.25; }
  .house-card-image { display:block; width:100%; height:190px; background:#0b0f13; overflow:hidden; }
  .house-card-image img { width:100%; height:100%; object-fit:cover; display:block; }
  .house-reject { position:absolute; right:10px; top:200px; z-index:2; }
  .house-actions { display:flex; gap:8px; align-items:center; margin-top:10px; }
  .house-actions .button { flex:1; margin:0; text-align:center; }
  .compact-score { display:flex; flex-wrap:wrap; gap:5px; margin:8px 0; }
  .candidate-card { display:grid; grid-template-columns:145px 1fr; gap:12px; overflow:hidden; padding:0; }
  .candidate-card img { width:145px; height:100%; min-height:150px; object-fit:cover; background:#0b0f13; }
  .candidate-body { padding:12px 12px 12px 0; min-width:0; }
  .candidate-actions { display:flex; flex-wrap:wrap; gap:7px; align-items:center; }
  .candidate-actions form { margin:0; }
  .settings-list { display:grid; gap:10px; }
  .empty-state { text-align:center; padding:28px 16px; }
  @media (max-width:680px) {
    .app-toolbar { justify-content:center; }
    .candidate-card { grid-template-columns:1fr; }
    .candidate-card img { width:100%; height:200px; }
    .candidate-body { padding:12px; }
    .house-actions .button { width:auto; }
    .candidate-actions .button, .candidate-actions button { width:100%; }
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


def ensure_focused_ui_schema() -> None:
    with connect() as con:
        ensure_columns(
            con,
            "houses",
            {
                "rejected_at": "TEXT",
                "rejection_reason": "TEXT",
            },
        )
        ensure_columns(
            con,
            "search_candidates",
            {
                "rejected_at": "TEXT",
                "rejection_reason": "TEXT",
                "decision": "TEXT",
            },
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_houses_status ON houses(status, created_at)")
        con.commit()


def _house_preview(house: dict[str, Any]) -> str:
    house_id = str(house.get("id") or "")
    local_images = [
        item
        for item in list_media(house_id)
        if item.get("kind") == "image" and item.get("download_status") == "downloaded" and item.get("id")
    ]
    if local_images:
        media_id = esc(local_images[-1].get("id"))
        return f'<img src="media/{media_id}" alt="Hausbild">'
    preview = str(house.get("preview_image_url") or "").strip()
    if preview:
        return f'<img src="{esc(preview)}" alt="Vorschaubild">'
    return '<div class="listing-no-image">Noch kein Bild</div>'


def _active_houses() -> list[dict[str, Any]]:
    return [house for house in list_houses() if str(house.get("status") or "new") != "rejected"]


def _rejected_houses() -> list[dict[str, Any]]:
    return [house for house in list_houses() if str(house.get("status") or "") == "rejected"]


def _candidate_rows(statuses: tuple[str, ...]) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in statuses)
    with connect() as con:
        rows = con.execute(
            f"""
            SELECT c.*, p.name AS profile_name
            FROM search_candidates c
            LEFT JOIN search_profiles p ON p.id = c.profile_id
            WHERE c.status IN ({placeholders})
            ORDER BY c.first_seen_at DESC
            """,
            statuses,
        ).fetchall()
    return [row_to_dict(row) or {} for row in rows]


def _deduplicated_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.get("external_id") or candidate.get("canonical_url") or candidate.get("source_url") or candidate.get("id"))
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def _house_card(house: dict[str, Any], *, rejected: bool = False) -> str:
    house_id = str(house.get("id") or "")
    score = house_score_result(house)
    status = get_pipeline_status(house_id)
    if rejected:
        actions = f"""
        <div class="house-actions">
          <form method="post" action="houses/{esc(house_id)}/restore" data-no-loading="true"><button class="secondary" type="submit">Wiederherstellen</button></form>
          <form method="post" action="houses/{esc(house_id)}/delete-permanent" data-no-loading="true" onsubmit="return confirm('Hausakte und alle Dateien endgültig löschen?');"><button class="danger" type="submit">Endgültig löschen</button></form>
        </div>
        """
        reject_button = ""
    else:
        actions = f'<div class="house-actions"><a class="button" href="houses/{esc(house_id)}">Hausakte öffnen</a></div>'
        reject_button = f"""
        <form class="house-reject" method="post" action="houses/{esc(house_id)}/reject" data-no-loading="true" onsubmit="return confirm('Dieses Objekt als abgelehnt markieren?');">
          <button class="icon-button danger" type="submit" title="Ablehnen" aria-label="Objekt ablehnen">🗑️</button>
        </form>
        """
    score_source = "KI" if score.get("source") == "ai" else "Vorprüfung"
    return f"""
    <article class="card house-card">
      <a class="house-card-image" href="houses/{esc(house_id)}">{_house_preview(house)}</a>
      {reject_button}
      <div class="house-card-body">
        <h3>{esc(house.get('title'))}</h3>
        <div class="muted">{esc(house.get('location_text') or 'Lage unbekannt')}</div>
        <div class="compact-score"><span class="pill {esc(score.get('pill'))}">{esc(score_source)} {esc(score.get('score'))}/100</span>{_pipeline_badge(status)}</div>
        <p><span class="pill">{money(house.get('price_eur'))}</span><span class="pill">{num(house.get('living_area_m2'), ' m² Wfl.')}</span><span class="pill">{num(house.get('plot_area_m2'), ' m² Grund')}</span><span class="pill">HWB {num(house.get('energy_hwb'))}</span></p>
        {f'<p class="muted">Abgelehnt: {esc(format_datetime(house.get("rejected_at")))}</p>' if rejected else ''}
        {actions}
      </div>
    </article>
    """


def _candidate_card(candidate: dict[str, Any], *, rejected: bool = False) -> str:
    candidate_id = str(candidate.get("id") or "")
    source_url = str(candidate.get("source_url") or "")
    preview = str(candidate.get("preview_image_url") or "").strip()
    image = f'<img src="{esc(preview)}" alt="Vorschaubild">' if preview else '<div class="listing-no-image">Kein Bild</div>'
    reasons = reasons_from_json(candidate.get("filter_reasons"))
    if rejected:
        actions = f"""
        <form method="post" action="search/candidates/{esc(candidate_id)}/restore" data-no-loading="true"><button class="secondary" type="submit">Wiederherstellen</button></form>
        <a class="button secondary" href="{esc(source_url)}" target="_blank">Inserat öffnen</a>
        """
    else:
        actions = f"""
        <form method="post" action="../import" data-loading="Inserat wird importiert, Medien werden geladen und die Analyse wird gestartet …">
          <input type="hidden" name="url" value="{esc(source_url)}"><input type="hidden" name="preview_image_url" value="{esc(preview)}"><button type="submit">Hausakte anlegen</button>
        </form>
        <form method="post" action="search/candidates/{esc(candidate_id)}/reject" data-no-loading="true" onsubmit="return confirm('Diesen Kandidaten ablehnen?');"><button class="danger" type="submit">🗑️ Ablehnen</button></form>
        <a class="button secondary" href="{esc(source_url)}" target="_blank">Inserat öffnen</a>
        """
    return f"""
    <article class="card candidate-card">
      <a href="{esc(source_url)}" target="_blank">{image}</a>
      <div class="candidate-body">
        <h3>{esc(candidate.get('title') or title_from_listing_url(source_url))}</h3>
        <p><span class="pill">{esc(candidate.get('profile_name') or 'Suchprofil')}</span><span class="pill">{money(candidate.get('price_eur'))}</span><span class="pill">{num(candidate.get('living_area_m2'), ' m² Wfl.')}</span><span class="pill">{num(candidate.get('plot_area_m2'), ' m² Grund')}</span><span class="pill">HWB {num(candidate.get('energy_hwb'))}</span></p>
        {candidate_score_html(candidate, str(candidate.get('status') or 'new'))}
        <p class="muted">{' · '.join(esc(reason) for reason in reasons[:4])}</p>
        <p class="muted">Erstmals: {esc(format_datetime(candidate.get('first_seen_at')))} · zuletzt: {esc(format_datetime(candidate.get('last_seen_at')))}</p>
        <div class="candidate-actions">{actions}</div>
      </div>
    </article>
    """


def _profile_settings_card(profile: dict[str, Any]) -> str:
    pid = str(profile.get("id") or "")
    enabled = bool(int(profile.get("enabled") or 0))
    mode = str(profile.get("automation_mode") or "manual")
    selected = lambda value: "selected" if mode == value else ""
    return f"""
    <div class="card">
      <h3>{esc(profile.get('name'))}</h3>
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


def _preserve_rejected_candidates(profile_id: str) -> None:
    original = getattr(_preserve_rejected_candidates, "original", None)
    if callable(original):
        original(profile_id)
    with connect() as con:
        con.execute("UPDATE search_candidates SET status = 'rejected' WHERE decision = 'rejected'")
        con.commit()


def register_focused_ui(app: FastAPI) -> None:
    ensure_focused_ui_schema()

    if not hasattr(_preserve_rejected_candidates, "original"):
        setattr(_preserve_rejected_candidates, "original", search_automation.sync_candidate_metadata)
        search_automation.sync_candidate_metadata = _preserve_rejected_candidates

    _remove_route(app, "/", "GET")
    _remove_route(app, "/search", "GET")

    @app.get("/", response_class=HTMLResponse)
    def focused_dashboard() -> HTMLResponse:
        houses = _active_houses()
        rejected_count = len(_rejected_houses()) + len(_candidate_rows(("rejected",)))
        body = f"""
        {FOCUS_CSS}
        <nav class="app-toolbar" aria-label="Aktionen">
          <a class="icon-button" href="import" title="Inserat hinzufügen" aria-label="Inserat hinzufügen">＋</a>
          <form method="post" action="search/run-all" data-loading="Willhaben wird durchsucht …"><button class="icon-button primary" type="submit" title="Suche starten" aria-label="Suche starten">🔍</button></form>
          <a class="icon-button toolbar-count" href="rejected" title="Abgelehnte Objekte" aria-label="Abgelehnte Objekte">🗑️{f'<span>{rejected_count}</span>' if rejected_count else ''}</a>
          <a class="icon-button" href="settings" title="Einstellungen" aria-label="Einstellungen">⚙️</a>
        </nav>
        <h2>Hausakten</h2>
        <div class="house-grid">{''.join(_house_card(house) for house in houses) if houses else '<div class="card empty-state"><h3>Noch keine aktiven Hausakten</h3><p class="muted">Starte die Suche über die Lupe oder füge ein Inserat hinzu.</p></div>'}</div>
        """
        return layout("Hausakten", body, home_href="./")

    @app.get("/search", response_class=HTMLResponse)
    def focused_search() -> HTMLResponse:
        candidates = _deduplicated_candidates(_candidate_rows(("new", "review")))
        profiles = [profile for profile in list_search_profiles() if bool(int(profile.get("enabled") or 0))]
        body = f"""
        {FOCUS_CSS}
        <nav class="app-toolbar">
          <a class="icon-button" href="./" title="Hausakten" aria-label="Hausakten">🏠</a>
          <form method="post" action="search/run-all" data-loading="Willhaben wird durchsucht …"><button class="icon-button primary" type="submit" title="Suche erneut starten" aria-label="Suche erneut starten">🔍</button></form>
          <a class="icon-button" href="settings/search" title="Suchprofile einstellen" aria-label="Suchprofile einstellen">⚙️</a>
        </nav>
        <div class="card">
          <h2>Suchergebnisse</h2>
          <p class="muted">{len(profiles)} aktive Suchprofile · {len(candidates)} offene Kandidaten. Die Lupe startet alle aktiven Profile sofort.</p>
        </div>
        <div class="listing-stack">{''.join(_candidate_card(candidate) for candidate in candidates) if candidates else '<div class="card empty-state"><h3>Keine offenen Kandidaten</h3><p class="muted">Starte die Suche oder passe die Suchprofile in den Einstellungen an.</p></div>'}</div>
        """
        return layout("Suche", body, home_href="../")

    @app.post("/search/run-all")
    async def run_all_profiles() -> RedirectResponse:
        for profile in list_search_profiles():
            if not bool(int(profile.get("enabled") or 0)):
                continue
            try:
                await execute_profile_cycle(str(profile["id"]), force=True)
            except Exception as exc:
                update_profile_automation(str(profile["id"]), {"last_run_status": "Fehler", "last_error": str(exc)[:1000]})
        return RedirectResponse("../search", status_code=303)

    @app.post("/search/candidates/{candidate_id}/reject")
    async def reject_candidate(candidate_id: str) -> RedirectResponse:
        if not get_search_candidate(candidate_id):
            raise HTTPException(status_code=404, detail="Kandidat nicht gefunden")
        with connect() as con:
            con.execute(
                "UPDATE search_candidates SET status = 'rejected', decision = 'rejected', rejected_at = ?, rejection_reason = ? WHERE id = ?",
                (now_iso(), "In der Kandidatenübersicht abgelehnt", candidate_id),
            )
            con.commit()
        return RedirectResponse("../../../search", status_code=303)

    @app.post("/search/candidates/{candidate_id}/restore")
    async def restore_candidate(candidate_id: str) -> RedirectResponse:
        candidate = get_search_candidate(candidate_id)
        if not candidate:
            raise HTTPException(status_code=404, detail="Kandidat nicht gefunden")
        restored_status = "imported" if candidate.get("imported_house_id") else "new"
        with connect() as con:
            con.execute(
                "UPDATE search_candidates SET status = ?, decision = ?, rejected_at = NULL, rejection_reason = NULL WHERE id = ?",
                (restored_status, restored_status, candidate_id),
            )
            con.commit()
        return RedirectResponse("../../../rejected", status_code=303)

    @app.post("/houses/{house_id}/reject")
    async def reject_house(house_id: str) -> RedirectResponse:
        if not get_house(house_id):
            raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")
        timestamp = now_iso()
        with connect() as con:
            con.execute(
                "UPDATE houses SET status = 'rejected', rejected_at = ?, rejection_reason = ?, updated_at = ? WHERE id = ?",
                (timestamp, "In der Hausaktenübersicht abgelehnt", timestamp, house_id),
            )
            con.execute(
                "UPDATE search_candidates SET status = 'rejected', decision = 'rejected', rejected_at = ?, rejection_reason = ? WHERE imported_house_id = ?",
                (timestamp, "Zugehörige Hausakte abgelehnt", house_id),
            )
            con.commit()
        return RedirectResponse("../../", status_code=303)

    @app.post("/houses/{house_id}/restore")
    async def restore_house(house_id: str) -> RedirectResponse:
        if not get_house(house_id):
            raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")
        timestamp = now_iso()
        with connect() as con:
            con.execute(
                "UPDATE houses SET status = 'new', rejected_at = NULL, rejection_reason = NULL, updated_at = ? WHERE id = ?",
                (timestamp, house_id),
            )
            con.execute(
                "UPDATE search_candidates SET status = 'imported', decision = 'imported', rejected_at = NULL, rejection_reason = NULL WHERE imported_house_id = ?",
                (house_id,),
            )
            con.commit()
        return RedirectResponse("../../rejected", status_code=303)

    @app.post("/houses/{house_id}/delete-permanent")
    async def delete_house_permanent(house_id: str) -> RedirectResponse:
        if not get_house(house_id):
            raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")
        with connect() as con:
            candidate_ids = [row[0] for row in con.execute("SELECT id FROM search_candidates WHERE imported_house_id = ?", (house_id,)).fetchall()]
        delete_house_full(house_id)
        if candidate_ids:
            placeholders = ",".join("?" for _ in candidate_ids)
            with connect() as con:
                con.execute(
                    f"UPDATE search_candidates SET status = 'rejected', decision = 'rejected', rejected_at = ?, rejection_reason = ?, imported_house_id = NULL WHERE id IN ({placeholders})",
                    [now_iso(), "Hausakte endgültig gelöscht"] + candidate_ids,
                )
                con.commit()
        return RedirectResponse("../../rejected", status_code=303)

    @app.get("/rejected", response_class=HTMLResponse)
    def rejected_objects() -> HTMLResponse:
        houses = _rejected_houses()
        candidates = _deduplicated_candidates([candidate for candidate in _candidate_rows(("rejected",)) if not candidate.get("imported_house_id")])
        body = f"""
        {FOCUS_CSS}
        <nav class="app-toolbar"><a class="icon-button" href="./" title="Hausakten" aria-label="Hausakten">🏠</a><a class="icon-button" href="search" title="Suche" aria-label="Suche">🔍</a></nav>
        <h2>Abgelehnte Objekte</h2>
        <p class="muted">Abgelehnte Hausakten bleiben erhalten und können wiederhergestellt oder endgültig gelöscht werden.</p>
        <div class="house-grid">{''.join(_house_card(house, rejected=True) for house in houses) if houses else '<div class="card muted">Keine abgelehnten Hausakten.</div>'}</div>
        <h2>Abgelehnte Kandidaten</h2>
        <div class="listing-stack">{''.join(_candidate_card(candidate, rejected=True) for candidate in candidates) if candidates else '<div class="card muted">Keine abgelehnten Kandidaten.</div>'}</div>
        """
        return layout("Abgelehnt", body, home_href="./")

    @app.get("/settings", response_class=HTMLResponse)
    def settings_home() -> HTMLResponse:
        body = f"""
        {FOCUS_CSS}
        <nav class="app-toolbar"><a class="icon-button" href="./" title="Hausakten" aria-label="Hausakten">🏠</a></nav>
        <h2>Einstellungen</h2>
        <div class="settings-list">
          <a class="card" href="settings/search" style="text-decoration:none;color:inherit"><h3>🔍 Suchprofile</h3><p class="muted">Regionen, Filter, Intervall und Automatikmodus verwalten.</p></a>
        </div>
        """
        return layout("Einstellungen", body, home_href="../")

    @app.get("/settings/search", response_class=HTMLResponse)
    def search_settings() -> HTMLResponse:
        profiles = list_search_profiles()
        body = f"""
        {FOCUS_CSS}
        <nav class="app-toolbar"><a class="icon-button" href="../" title="Einstellungen" aria-label="Einstellungen">←</a><a class="icon-button" href="../../search" title="Suchergebnisse" aria-label="Suchergebnisse">🔍</a></nav>
        <h2>Suchprofile</h2>
        <div class="settings-list">{''.join(_profile_settings_card(profile) for profile in profiles) if profiles else '<div class="card muted">Noch keine Suchprofile vorhanden.</div>'}</div>
        <div class="card">
          <details>
            <summary><strong>Neues Suchprofil anlegen</strong></summary>
            <form method="post" action="search/profiles" data-loading="Suchprofil wird gespeichert …">
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
          </details>
        </div>
        """
        return layout("Suchprofile", body, home_href="../../")

    @app.post("/settings/search/profiles")
    async def create_profile_in_settings(
        name: str = Form(...),
        search_url: str | None = Form(None),
        area_ids: str | None = Form("8551"),
        regions: str | None = Form(None),
        max_price_eur: str | None = Form(None),
        soft_max_price_eur: str | None = Form(None),
        min_living_area_m2: str | None = Form(None),
        min_plot_area_m2: str | None = Form(None),
        exclude_roads: str | None = Form(None),
        hwb_warn: str | None = Form(None),
        hwb_reject: str | None = Form(None),
        oil_policy: str | None = Form("review"),
        automation_mode: str | None = Form("review"),
        run_interval_minutes: int = Form(60),
        max_results: int = Form(80),
        auto_import_min_score: int = Form(68),
        auto_import_limit_per_run: int = Form(2),
    ) -> RedirectResponse:
        def as_int(value: str | None) -> int | None:
            try:
                return int(float(str(value))) if str(value or "").strip() else None
            except Exception:
                return None

        def as_float(value: str | None) -> float | None:
            try:
                return float(str(value).replace(",", ".")) if str(value or "").strip() else None
            except Exception:
                return None

        mode = automation_mode if automation_mode in {"manual", "review", "automatic"} else "review"
        profile_data: dict[str, Any] = {
            "name": name.strip(),
            "source_name": "willhaben.at",
            "max_price_eur": as_int(max_price_eur),
            "soft_max_price_eur": as_int(soft_max_price_eur),
            "min_living_area_m2": as_float(min_living_area_m2),
            "min_plot_area_m2": as_float(min_plot_area_m2),
            "regions": str(regions or "").strip(),
            "exclude_roads": exclude_roads,
            "hwb_warn": as_float(hwb_warn),
            "hwb_reject": as_float(hwb_reject),
            "oil_policy": oil_policy or "review",
        }
        raw_url = str(search_url or "").strip()
        if raw_url:
            if not raw_url.startswith(("http://", "https://")) or "willhaben.at" not in raw_url.lower():
                raise HTTPException(status_code=400, detail="Aktuell werden nur gültige Willhaben-Such-URLs unterstützt")
            profile_data["search_url"] = raw_url
        else:
            profile_data["search_url"] = "\n".join(build_willhaben_auto_urls(profile_data, area_ids))
        profile = create_search_profile(profile_data)
        update_profile_automation(
            str(profile["id"]),
            {
                "enabled": 1,
                "area_ids": str(area_ids or "").strip(),
                "automation_mode": mode,
                "run_interval_minutes": max(15, min(int(run_interval_minutes or 60), 1440)),
                "auto_import_enabled": 1 if mode == "automatic" else 0,
                "max_results": max(10, min(int(max_results or 80), 160)),
                "auto_import_min_score": max(0, min(int(auto_import_min_score or 68), 100)),
                "auto_import_limit_per_run": max(1, min(int(auto_import_limit_per_run or 2), 10)),
                "last_run_status": "bereit",
            },
        )
        return RedirectResponse("../search", status_code=303)

    @app.post("/settings/search/profiles/{profile_id}")
    async def update_profile_in_settings(
        profile_id: str,
        enabled: int = Form(1),
        automation_mode: str = Form("review"),
        run_interval_minutes: int = Form(60),
        max_results: int = Form(80),
        auto_import_min_score: int = Form(68),
        auto_import_limit_per_run: int = Form(2),
    ) -> RedirectResponse:
        if not get_search_profile(profile_id):
            raise HTTPException(status_code=404, detail="Suchprofil nicht gefunden")
        mode = automation_mode if automation_mode in {"manual", "review", "automatic"} else "review"
        update_profile_automation(
            profile_id,
            {
                "enabled": 1 if enabled else 0,
                "automation_mode": mode,
                "run_interval_minutes": max(15, min(int(run_interval_minutes or 60), 1440)),
                "auto_import_enabled": 1 if mode == "automatic" else 0,
                "max_results": max(10, min(int(max_results or 80), 160)),
                "auto_import_min_score": max(0, min(int(auto_import_min_score or 68), 100)),
                "auto_import_limit_per_run": max(1, min(int(auto_import_limit_per_run or 2), 10)),
                "last_run_status": "Einstellungen aktualisiert",
                "last_error": None,
            },
        )
        return RedirectResponse("../../search", status_code=303)
