from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from app.analysis_package import load_analysis
from app.github_auto_export import auto_export_house_to_github
from app.house_manage import (
    delete_house_form_html,
    edit_house_form_html,
    expose_upload_html,
    hero_gallery_html,
    image_grid_html,
)
from app.main import (
    build_willhaben_auto_urls,
    criteria_summary,
    download_pending_media_files,
    layout,
    money,
    num,
    reasons_from_json,
    resolve_search_urls,
    run_search_profile,
    source_url_exists,
    status_pill,
    title_from_listing_url,
    visible_candidates,
)
from app.pipeline_status import (
    ensure_pipeline_schema,
    get_pipeline_status,
    list_pipeline_events,
    pipeline_counts,
    set_pipeline_stage,
)
from app.storage import (
    connect,
    create_search_profile,
    ensure_columns,
    get_house,
    get_search_profile,
    list_evidence,
    list_houses,
    list_media,
    list_search_candidates,
    list_search_profiles,
    list_sources,
    now_iso,
    row_to_dict,
)
from app.ui_helpers import candidate_score_html, esc, house_score_html


PRODUCT_CSS = """
<style>
  .top-actions { display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
  .top-actions form { margin:0; }
  .status-steps { display:grid; gap:8px; margin:12px 0; }
  .status-step { display:grid; grid-template-columns:26px 1fr; gap:9px; align-items:start; padding:9px 10px; border-radius:11px; background:#111a22; border:1px solid #26323e; }
  .status-icon { width:22px; height:22px; border-radius:50%; display:grid; place-items:center; font-size:13px; font-weight:800; background:#394957; }
  .status-step.done .status-icon { background:#245c3a; }
  .status-step.active .status-icon { background:#6b5422; }
  .status-step.error .status-icon { background:#6b2d2d; }
  .status-step strong { display:block; }
  .status-step small { color:#aab4bd; }
  .dashboard-metrics { display:flex; flex-wrap:wrap; gap:6px; }
  .subtle-box { background:#111a22; border:1px solid #26323e; border-radius:12px; padding:10px; }
  details.tech-details > summary { cursor:pointer; padding:6px 0; }
  .profile-mode { text-transform:none; }
  @media (max-width:680px) { .top-actions, .top-actions form, .top-actions button, .top-actions .button { width:100%; } }
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


def ensure_search_foundation_schema() -> None:
    with connect() as con:
        ensure_columns(
            con,
            "search_profiles",
            {
                "area_ids": "TEXT",
                "automation_mode": "TEXT NOT NULL DEFAULT 'manual'",
                "run_interval_minutes": "INTEGER NOT NULL DEFAULT 60",
                "auto_import_enabled": "INTEGER NOT NULL DEFAULT 0",
                "max_results": "INTEGER NOT NULL DEFAULT 80",
                "last_run_status": "TEXT",
                "last_error": "TEXT",
            },
        )
        ensure_columns(
            con,
            "search_candidates",
            {
                "provider": "TEXT NOT NULL DEFAULT 'willhaben.at'",
                "external_id": "TEXT",
                "canonical_url": "TEXT",
                "content_hash": "TEXT",
                "last_changed_at": "TEXT",
                "offline_at": "TEXT",
                "decision": "TEXT",
                "raw_data_json": "TEXT",
                "change_count": "INTEGER NOT NULL DEFAULT 0",
            },
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_search_candidates_external ON search_candidates(provider, external_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_search_candidates_status ON search_candidates(profile_id, status)")
        con.commit()


def _external_id(url: str) -> str | None:
    match = re.search(r"-(\d{7,})(?:$|[/?#])", url or "")
    return match.group(1) if match else None


def _canonical_url(url: str) -> str:
    return str(url or "").split("?", 1)[0].split("#", 1)[0].rstrip("/")


def _candidate_hash(candidate: dict[str, Any]) -> str:
    payload = {
        "title": candidate.get("title"),
        "price_eur": candidate.get("price_eur"),
        "living_area_m2": candidate.get("living_area_m2"),
        "plot_area_m2": candidate.get("plot_area_m2"),
        "energy_hwb": candidate.get("energy_hwb"),
        "preview_image_url": candidate.get("preview_image_url"),
        "status": candidate.get("status"),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def sync_candidate_foundation(profile_id: str) -> None:
    ensure_search_foundation_schema()
    timestamp = now_iso()
    candidates = list_search_candidates(profile_id)
    with connect() as con:
        for candidate in candidates:
            source_url = str(candidate.get("source_url") or "")
            new_hash = _candidate_hash(candidate)
            old_hash = str(candidate.get("content_hash") or "")
            changed = bool(old_hash and old_hash != new_hash)
            raw_data = {
                "title": candidate.get("title"),
                "price_eur": candidate.get("price_eur"),
                "living_area_m2": candidate.get("living_area_m2"),
                "plot_area_m2": candidate.get("plot_area_m2"),
                "energy_hwb": candidate.get("energy_hwb"),
                "preview_image_url": candidate.get("preview_image_url"),
                "filter_reasons": reasons_from_json(candidate.get("filter_reasons")),
            }
            con.execute(
                """
                UPDATE search_candidates
                SET provider = 'willhaben.at',
                    external_id = COALESCE(external_id, ?),
                    canonical_url = ?,
                    content_hash = ?,
                    last_changed_at = CASE
                        WHEN last_changed_at IS NULL OR ? = 1 THEN ?
                        ELSE last_changed_at
                    END,
                    change_count = change_count + ?,
                    decision = COALESCE(decision, status),
                    raw_data_json = ?
                WHERE id = ?
                """,
                (
                    _external_id(source_url),
                    _canonical_url(source_url),
                    new_hash,
                    1 if changed else 0,
                    timestamp,
                    1 if changed else 0,
                    json.dumps(raw_data, ensure_ascii=False),
                    candidate["id"],
                ),
            )
        con.commit()


def update_profile_foundation(profile_id: str, data: dict[str, Any]) -> None:
    ensure_search_foundation_schema()
    allowed = {
        "area_ids",
        "automation_mode",
        "run_interval_minutes",
        "auto_import_enabled",
        "max_results",
        "last_run_status",
        "last_error",
    }
    fields = {key: value for key, value in data.items() if key in allowed}
    if not fields:
        return
    fields["updated_at"] = now_iso()
    sql = ", ".join(f"{key} = ?" for key in fields)
    with connect() as con:
        con.execute(f"UPDATE search_profiles SET {sql} WHERE id = ?", list(fields.values()) + [profile_id])
        con.commit()


def _mode_label(value: object) -> str:
    return {
        "manual": "manuell",
        "review": "halbautomatisch vorbereitet",
        "automatic": "vollautomatisch vorbereitet",
    }.get(str(value or "manual"), "manuell")


def _pipeline_badge(status: dict[str, Any]) -> str:
    stage = str(status.get("stage") or "created")
    state = str(status.get("state") or "pending")
    css = "bad" if state == "error" or stage == "error" else "good" if stage == "completed" else "warn"
    return f"<span class='pill {css}'>{esc(status.get('stage_label'))}</span>"


def _pipeline_step(label: str, done: bool, active: bool, detail: str, error: bool = False) -> str:
    css = "error" if error else "done" if done else "active" if active else ""
    icon = "!" if error else "✓" if done else "…" if active else "·"
    return f"<div class='status-step {css}'><span class='status-icon'>{icon}</span><div><strong>{esc(label)}</strong><small>{esc(detail)}</small></div></div>"


def pipeline_card_html(house_id: str) -> str:
    status = get_pipeline_status(house_id)
    analysis_done = bool(status.get("analysis_exists"))
    source_done = int(status.get("source_count") or 0) > 0
    media_done = int(status.get("downloaded_count") or 0) > 0 and int(status.get("pending_count") or 0) == 0
    exported = bool(status.get("exported_at"))
    failed = int(status.get("failed_count") or 0)
    state_error = str(status.get("state") or "") == "error"

    steps = [
        _pipeline_step("Inserat erfasst", source_done, not source_done, f"{status.get('source_count', 0)} Quelle(n) gespeichert"),
        _pipeline_step(
            "Medien geladen",
            media_done,
            source_done and not media_done,
            f"{status.get('downloaded_count', 0)} geladen · {status.get('pending_count', 0)} offen · {failed} Fehler",
            error=failed > 0 and not media_done,
        ),
        _pipeline_step(
            "Zur Analyse bereitgestellt",
            exported,
            media_done and not exported,
            str(status.get("exported_at") or "ZIP wird nach GitHub exportiert"),
            error=state_error and not exported,
        ),
        _pipeline_step(
            "ChatGPT-Analyse importiert",
            analysis_done,
            exported and not analysis_done,
            str(status.get("analysis_imported_at") or ("Ergebnis wird automatisch übernommen" if exported else "wartet auf Export")),
            error=state_error and exported and not analysis_done,
        ),
    ]
    error_html = f"<p class='danger'><strong>Letzter Fehler:</strong> {esc(status.get('last_error'))}</p>" if status.get("last_error") else ""
    return f"""
    <div class="card">
      <h2>Verarbeitungsstatus</h2>
      <p>{_pipeline_badge(status)}<span class="pill">aktualisiert: {esc(status.get('updated_at') or '–')}</span></p>
      <div class="status-steps">{''.join(steps)}</div>
      {error_html}
      <form method="post" action="{esc(house_id)}/analysis/retry" data-loading="Analysepaket wird erneut bereitgestellt …">
        <button type="submit">Analyse erneut anstoßen</button>
      </form>
    </div>
    """


def analysis_card_html(house_id: str) -> str:
    analysis = load_analysis(house_id)
    if not analysis:
        return """
        <div class="card">
          <h2>ChatGPT-Analyse</h2>
          <p class="muted">Noch kein Ergebnis vorhanden. Der automatische Prozess übernimmt Export und Rückimport.</p>
        </div>
        """
    positives = analysis.get("positive_findings") or []
    risks = analysis.get("risk_findings") or []
    positive_html = "".join(f"<li>{esc(item)}</li>" for item in positives[:6]) or "<li class='muted'>Keine Chancen eingetragen.</li>"
    risk_html = "".join(f"<li>{esc(item)}</li>" for item in risks[:6]) or "<li class='muted'>Keine Risiken eingetragen.</li>"
    return f"""
    <div class="card">
      <h2>ChatGPT-Analyse</h2>
      <p><span class="pill good">KI-Score {esc(analysis.get('new_score'))}/100</span><span class="pill">Sicherheit: {esc(analysis.get('confidence'))}</span><span class="pill">{esc(analysis.get('analysis_date'))}</span></p>
      <p>{esc(analysis.get('summary') or '')}</p>
      <p><strong>Empfehlung:</strong> {esc(analysis.get('recommendation') or '')}</p>
      <div class="grid"><div><strong>Chancen</strong><ul>{positive_html}</ul></div><div><strong>Risiken</strong><ul>{risk_html}</ul></div></div>
    </div>
    """


def diagnostics_html(house_id: str) -> str:
    media = list_media(house_id)
    sources = list_sources(house_id)
    evidence = list_evidence(house_id)
    events = list_pipeline_events(house_id)
    source_rows = "".join(
        f"<tr><td>{esc(item.get('source_name'))}</td><td><a href='{esc(item.get('source_url'))}' target='_blank'>Direktlink</a></td><td>{esc(item.get('parser_status'))}</td></tr>"
        for item in sources
    )
    evidence_rows = "".join(
        f"<tr><td>{esc(item.get('field_name'))}</td><td>{esc(item.get('value_text'))}</td><td>{esc(item.get('confidence'))}</td><td>{esc(item.get('source_text_snippet'))}</td></tr>"
        for item in evidence[:40]
    )
    event_rows = "".join(
        f"<tr><td>{esc(item.get('created_at'))}</td><td>{esc(item.get('stage'))}</td><td>{esc(item.get('state'))}</td><td>{esc(item.get('message'))}</td></tr>"
        for item in events
    )
    failed_rows = "".join(
        f"<tr><td>{esc(item.get('kind'))}</td><td>{esc(item.get('original_url'))}</td><td class='danger'>{esc(item.get('download_error'))}</td></tr>"
        for item in media
        if item.get("download_status") == "failed"
    )
    return f"""
    <div class="card compact-card">
      <details class="tech-details">
        <summary><strong>Diagnose und technische Details</strong></summary>
        <p class="muted">Die frühere GitHub-, Base64-, Gmail- und manuelle Analysepaket-Bedienung ist aus der normalen Oberfläche entfernt. Die automatische Pipeline bleibt aktiv.</p>
        <div class="top-actions">
          <form method="post" action="{esc(house_id)}/download-media" data-loading="Medien werden heruntergeladen …"><button class="secondary" type="submit">Medien erneut laden</button></form>
          <form method="post" action="{esc(house_id)}/cleanup-media" data-loading="Medien werden bereinigt …"><button class="secondary" type="submit">Medien bereinigen</button></form>
        </div>
        <h3>Pipeline-Ereignisse</h3><table><tr><th>Zeit</th><th>Stufe</th><th>Status</th><th>Meldung</th></tr>{event_rows or '<tr><td colspan="4" class="muted">Noch keine Ereignisse.</td></tr>'}</table>
        <h3>Quellen</h3><table><tr><th>Quelle</th><th>Link</th><th>Status</th></tr>{source_rows}</table>
        <h3>Feldherkunft</h3><table><tr><th>Feld</th><th>Wert</th><th>Sicherheit</th><th>Snippet</th></tr>{evidence_rows}</table>
        {f'<h3>Medienfehler</h3><table><tr><th>Typ</th><th>URL</th><th>Fehler</th></tr>{failed_rows}</table>' if failed_rows else ''}
      </details>
    </div>
    """


def _candidate_totals() -> dict[str, int]:
    ensure_search_foundation_schema()
    with connect() as con:
        rows = con.execute("SELECT status, COUNT(*) AS count FROM search_candidates GROUP BY status").fetchall()
    result = {str(row["status"]): int(row["count"]) for row in rows}
    return {
        "new": result.get("new", 0),
        "review": result.get("review", 0),
        "filtered": result.get("filtered", 0),
        "imported": result.get("imported", 0),
    }


def register_product_ui(app: FastAPI) -> None:
    ensure_pipeline_schema()
    ensure_search_foundation_schema()

    for path, method in [
        ("/", "GET"),
        ("/search", "GET"),
        ("/search/profiles", "POST"),
        ("/search/profiles/{profile_id}", "GET"),
        ("/search/profiles/{profile_id}/run", "POST"),
        ("/houses/{house_id}", "GET"),
    ]:
        _remove_route(app, path, method)

    @app.get("/", response_class=HTMLResponse)
    def dashboard_product() -> HTMLResponse:
        houses = list_houses()
        profiles = list_search_profiles()
        pcounts = pipeline_counts()
        ccounts = _candidate_totals()
        cards: list[str] = []
        for house in houses:
            hid = str(house.get("id") or "")
            status = get_pipeline_status(hid)
            image = ""
            local_images = [item for item in list_media(hid) if item.get("kind") == "image" and item.get("download_status") == "downloaded"]
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
        body = f"""
        {PRODUCT_CSS}
        <div class="grid">
          <div class="card">
            <h2>Objekt hinzufügen</h2>
            <p class="muted">Direktlink importieren oder über ein Suchprofil Kandidaten sammeln.</p>
            <div class="top-actions"><a class="button" href="import">Inserat importieren</a><a class="button secondary" href="search">Suchprofile</a></div>
          </div>
          <div class="card">
            <h2>Pipeline</h2>
            <div class="dashboard-metrics"><span class="pill">{len(houses)} Hausakten</span><span class="pill warn">{pcounts['waiting']} warten auf Analyse</span><span class="pill good">{pcounts['completed']} abgeschlossen</span><span class="pill bad">{pcounts['errors']} Fehler</span></div>
            <p class="muted">Export, GitHub-Artifact, ChatGPT-Auswertung und Rückimport laufen automatisch.</p>
          </div>
          <div class="card">
            <h2>Suche vorbereitet</h2>
            <div class="dashboard-metrics"><span class="pill">{len(profiles)} Profile</span><span class="pill good">{ccounts['new']} neu</span><span class="pill warn">{ccounts['review']} prüfen</span><span class="pill">{ccounts['imported']} importiert</span></div>
            <p class="muted">Suchprofile und Kandidatenhistorie sind für die nächste automatische Willhaben-Stufe vorbereitet.</p>
          </div>
        </div>
        <h2>Hausakten</h2>
        <div class="grid">{''.join(cards) if cards else '<div class="card muted">Noch keine Objekte vorhanden.</div>'}</div>
        """
        return layout("HausCheck", body, home_href="./")

    @app.get("/search", response_class=HTMLResponse)
    def search_profiles_product() -> HTMLResponse:
        profiles = list_search_profiles()
        rows: list[str] = []
        for profile in profiles:
            sync_candidate_foundation(str(profile["id"]))
            candidates = visible_candidates(list_search_candidates(str(profile["id"])))
            counts = {status: len([item for item in candidates if str(item.get("status") or "new") == status]) for status in ["new", "review", "filtered", "imported"]}
            rows.append(
                f"""
                <tr>
                  <td><strong>{esc(profile.get('name'))}</strong><br>{criteria_summary(profile)}</td>
                  <td><span class="pill profile-mode">{esc(_mode_label(profile.get('automation_mode')))}</span><br><span class="muted">alle {esc(profile.get('run_interval_minutes') or 60)} Min. vorbereitet</span></td>
                  <td><span class="pill good">{counts['new']} neu</span><span class="pill warn">{counts['review']} prüfen</span><span class="pill bad">{counts['filtered']} gefiltert</span><span class="pill">{counts['imported']} importiert</span></td>
                  <td>{esc(profile.get('last_run_at') or 'noch nie')}<br><span class="muted">{esc(profile.get('last_run_status') or '')}</span></td>
                  <td><a class="button" href="search/profiles/{esc(profile['id'])}">Öffnen</a></td>
                </tr>
                """
            )
        body = f"""
        {PRODUCT_CSS}
        <div class="card">
          <h2>Suchprofil anlegen</h2>
          <p class="muted">Die Datenbank speichert bereits Portal-ID, kanonische URL, Erstfund, letzte Sichtung und Änderungen. Die zeitgesteuerte Vollautomatik folgt im nächsten Schritt.</p>
          <form method="post" action="search/profiles" data-loading="Suchprofil wird gespeichert …">
            <label>Name</label><input name="name" placeholder="z. B. Familienhaus Südweststeiermark" required>
            <label>Regionen / Orte</label><input name="regions" value="Wies, Eibiswald, Oberhaag, Gleinstätten, Bad Schwanberg, Pölfing-Brunn, Frauental, Deutschlandsberg">
            <label>Willhaben PLZ / areaIds</label><input name="area_ids" value="8551,8552,8544,8553" placeholder="z. B. 8551,8552,8544,8553">
            <label>Willhaben-Suchergebnis-URL optional</label><input name="search_url" placeholder="leer lassen = automatische URL aus den areaIds">
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
              <div><label>Automatikmodus vorbereiten</label><select name="automation_mode"><option value="manual">manuell</option><option value="review" selected>halbautomatisch</option><option value="automatic">vollautomatisch</option></select></div>
              <div><label>Suchintervall Minuten</label><input name="run_interval_minutes" type="number" value="60" min="15"></div>
              <div><label>Max. Treffer je Lauf</label><input name="max_results" type="number" value="80" min="10" max="160"></div>
            </div>
            <button type="submit">Suchprofil speichern</button>
          </form>
        </div>
        <div class="card"><h2>Gespeicherte Profile</h2><table><tr><th>Profil</th><th>Modus</th><th>Kandidaten</th><th>Letzter Lauf</th><th></th></tr>{''.join(rows) if rows else '<tr><td colspan="5" class="muted">Noch keine Suchprofile gespeichert.</td></tr>'}</table></div>
        """
        return layout("Suchprofile", body, home_href="../")

    @app.post("/search/profiles")
    def create_profile_product(
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
        automation_mode: str | None = Form("manual"),
        run_interval_minutes: int = Form(60),
        max_results: int = Form(80),
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
        update_profile_foundation(
            str(profile["id"]),
            {
                "area_ids": str(area_ids or "").strip(),
                "automation_mode": automation_mode if automation_mode in {"manual", "review", "automatic"} else "manual",
                "run_interval_minutes": max(15, min(int(run_interval_minutes or 60), 1440)),
                "auto_import_enabled": 0,
                "max_results": max(10, min(int(max_results or 80), 160)),
                "last_run_status": "bereit",
            },
        )
        return RedirectResponse(f"profiles/{profile['id']}", status_code=303)

    @app.get("/search/profiles/{profile_id}", response_class=HTMLResponse)
    def profile_detail_product(profile_id: str) -> HTMLResponse:
        profile = get_search_profile(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Suchprofil nicht gefunden")
        sync_candidate_foundation(profile_id)
        candidates = visible_candidates(list_search_candidates(profile_id))
        cards: list[str] = []
        for candidate in candidates:
            source_url = str(candidate.get("source_url") or "")
            imported = candidate.get("status") == "imported" or source_url_exists(source_url)
            status = "imported" if imported else str(candidate.get("status") or "new")
            preview = str(candidate.get("preview_image_url") or "").strip()
            preview_html = f'<a class="listing-image" href="{esc(source_url)}" target="_blank"><img src="{esc(preview)}" alt="Vorschaubild"></a>' if preview else f'<a class="listing-image" href="{esc(source_url)}" target="_blank"><div class="listing-no-image">kein Bild</div></a>'
            reasons = reasons_from_json(candidate.get("filter_reasons"))
            action = ""
            if not imported and status != "filtered":
                action = f"""
                <form method="post" action="../../import" data-loading="Inserat wird importiert, Medien werden geladen und die Analyse wird gestartet …">
                  <input type="hidden" name="url" value="{esc(source_url)}"><input type="hidden" name="preview_image_url" value="{esc(preview)}"><button type="submit">Hausakte anlegen & analysieren</button>
                </form>
                """
            elif imported:
                house_id = candidate.get("imported_house_id")
                action = f'<a class="button" href="../../../houses/{esc(house_id)}">Hausakte öffnen</a>' if house_id else "<span class='muted'>bereits importiert</span>"
            else:
                action = "<span class='muted'>ausgefiltert</span>"
            try:
                score_html = candidate_score_html(candidate, status)
            except Exception:
                score_html = ""
            cards.append(
                f"""
                <article class="listing-card">
                  {preview_html}
                  <div class="listing-body">
                    <a class="listing-title" href="{esc(source_url)}" target="_blank">{esc(candidate.get('title') or title_from_listing_url(source_url))}</a>
                    <div>{status_pill(status)}<span class="pill">ID {esc(candidate.get('external_id') or '–')}</span></div>
                    {score_html}
                    <div class="listing-facts"><span class="pill">{money(candidate.get('price_eur'))}</span><span class="pill">{num(candidate.get('living_area_m2'), ' m² Wfl.')}</span><span class="pill">{num(candidate.get('plot_area_m2'), ' m² Grund')}</span><span class="pill">HWB {num(candidate.get('energy_hwb'))}</span></div>
                    <div class="listing-reasons">{'<br>'.join(esc(item) for item in reasons[:4])}</div>
                    <p class="muted">Erstmals: {esc(candidate.get('first_seen_at'))} · zuletzt: {esc(candidate.get('last_seen_at'))} · Änderungen: {esc(candidate.get('change_count') or 0)}</p>
                    <div class="listing-actions">{action}<a class="button secondary" href="{esc(source_url)}" target="_blank">Bei Willhaben öffnen</a></div>
                  </div>
                </article>
                """
            )
        source_links = "<br>".join(f'<a href="{esc(url)}" target="_blank">Willhaben-Suchquelle {index}</a>' for index, url in enumerate(resolve_search_urls(profile), start=1))
        body = f"""
        {PRODUCT_CSS}
        <div class="card">
          <h2>{esc(profile.get('name'))}</h2>
          <p>{criteria_summary(profile)}</p>
          <p><span class="pill">Modus: {esc(_mode_label(profile.get('automation_mode')))}</span><span class="pill">Intervall: {esc(profile.get('run_interval_minutes') or 60)} Min.</span><span class="pill">{len(candidates)} Kandidaten</span></p>
          <p class="muted source-links">{source_links}</p>
          <div class="top-actions"><form method="post" action="{esc(profile_id)}/run" data-loading="Suchprofil wird gestartet. Kandidaten werden gesucht und geprüft …"><button type="submit">Suche jetzt ausführen</button></form><a class="button secondary" href="../../search">Zurück</a></div>
          {f'<p class="danger">Letzter Fehler: {esc(profile.get("last_error"))}</p>' if profile.get('last_error') else ''}
        </div>
        <section class="listing-stack">{''.join(cards) if cards else '<div class="card muted">Noch keine Kandidaten. Starte die Suche.</div>'}</section>
        """
        return layout("Suchprofil", body, home_href="../../../")

    @app.post("/search/profiles/{profile_id}/run")
    async def run_profile_product(profile_id: str) -> RedirectResponse:
        profile = get_search_profile(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Suchprofil nicht gefunden")
        update_profile_foundation(profile_id, {"last_run_status": "läuft", "last_error": None})
        try:
            await run_search_profile(profile_id, int(profile.get("max_results") or 80))
            sync_candidate_foundation(profile_id)
            update_profile_foundation(profile_id, {"last_run_status": "erfolgreich", "last_error": None})
        except Exception as exc:
            update_profile_foundation(profile_id, {"last_run_status": "Fehler", "last_error": str(exc)[:1000]})
            raise
        return RedirectResponse(f"../{profile_id}", status_code=303)

    @app.get("/houses/{house_id}", response_class=HTMLResponse)
    def house_detail_product(house_id: str) -> HTMLResponse:
        house = get_house(house_id)
        if not house:
            raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")
        body = f"""
        {PRODUCT_CSS}
        {hero_gallery_html(house_id)}
        <div class="card">
          <h2>{esc(house.get('title'))}</h2>
          <p class="muted">{esc(house.get('location_text') or 'Lage unbekannt')}</p>
          {house_score_html(house)}
          <p><span class="pill">{money(house.get('price_eur'))}</span><span class="pill">{num(house.get('living_area_m2'), ' m² Wfl.')}</span><span class="pill">{num(house.get('plot_area_m2'), ' m² Grund')}</span><span class="pill">HWB {num(house.get('energy_hwb'))}</span><span class="pill">fGEE {num(house.get('energy_fgee'))}</span><span class="pill">Heizung: {esc(house.get('heating') or 'unbekannt')}</span></p>
        </div>
        {pipeline_card_html(house_id)}
        {analysis_card_html(house_id)}
        {edit_house_form_html(house)}
        {expose_upload_html(house_id)}
        <div class="card"><h2>Bilder</h2><div class="gallery">{image_grid_html(house_id)}</div></div>
        {diagnostics_html(house_id)}
        {delete_house_form_html(house_id)}
        """
        return layout(str(house.get("title") or "Hausakte"), body, home_href="../../")

    @app.post("/houses/{house_id}/analysis/retry")
    async def retry_analysis_product(house_id: str) -> RedirectResponse:
        if not get_house(house_id):
            raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")
        set_pipeline_stage(house_id, "exporting", "running", "Analysepaket wird erneut erstellt und nach GitHub exportiert.")
        ok = await auto_export_house_to_github(house_id)
        if not ok:
            set_pipeline_stage(house_id, "error", "error", "Analyse konnte nicht erneut angestoßen werden.")
        return RedirectResponse(f"../{house_id}", status_code=303)
