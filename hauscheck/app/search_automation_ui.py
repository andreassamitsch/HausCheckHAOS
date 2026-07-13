from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from app.main import build_willhaben_auto_urls, criteria_summary, layout, visible_candidates
from app.product_ui import PRODUCT_CSS
from app.search_automation import (
    ensure_search_automation_schema,
    execute_profile_cycle,
    update_profile_automation,
)
from app.storage import create_search_profile, get_search_profile, list_search_candidates, list_search_profiles
from app.ui_helpers import esc


def _methods(route: Any) -> set[str]:
    return set(getattr(route, "methods", set()) or set())


def _remove_route(app: FastAPI, path: str, method: str) -> None:
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (getattr(route, "path", "") == path and method in _methods(route))
    ]


def _mode_label(value: object) -> str:
    return {
        "manual": "manuell",
        "review": "automatisch suchen, manuell importieren",
        "automatic": "automatisch suchen und importieren",
    }.get(str(value or "manual"), "manuell")


def _selected(current: object, value: str) -> str:
    return "selected" if str(current or "") == value else ""


def _as_int(value: str | int | None, default: int | None = None) -> int | None:
    try:
        return int(float(str(value))) if str(value or "").strip() else default
    except Exception:
        return default


def _as_float(value: str | float | None) -> float | None:
    try:
        return float(str(value).replace(",", ".")) if str(value or "").strip() else None
    except Exception:
        return None


def _profile_counts(profile_id: str) -> dict[str, int]:
    candidates = visible_candidates(list_search_candidates(profile_id))
    return {
        status: len([item for item in candidates if str(item.get("status") or "new") == status])
        for status in ["new", "review", "filtered", "imported"]
    }


def register_search_automation_ui(app: FastAPI) -> None:
    ensure_search_automation_schema()
    _remove_route(app, "/search", "GET")
    _remove_route(app, "/search/profiles", "POST")
    _remove_route(app, "/search/profiles/{profile_id}/run", "POST")

    @app.get("/search", response_class=HTMLResponse)
    def search_profiles_automatic() -> HTMLResponse:
        profiles = list_search_profiles()
        profile_cards: list[str] = []
        for profile in profiles:
            pid = str(profile["id"])
            counts = _profile_counts(pid)
            enabled = bool(int(profile.get("enabled") or 0))
            mode = str(profile.get("automation_mode") or "manual")
            error_html = (
                f'<p class="danger"><strong>Letzter Fehler:</strong> {esc(profile.get("last_error"))}</p>'
                if profile.get("last_error")
                else ""
            )
            profile_cards.append(
                f"""
                <div class="card">
                  <h3>{esc(profile.get('name'))}</h3>
                  <p>{criteria_summary(profile)}</p>
                  <p>
                    <span class="pill {'good' if enabled else 'bad'}">{'aktiv' if enabled else 'pausiert'}</span>
                    <span class="pill">{esc(_mode_label(mode))}</span>
                    <span class="pill">alle {esc(profile.get('run_interval_minutes') or 60)} Min.</span>
                  </p>
                  <p>
                    <span class="pill good">{counts['new']} neu</span>
                    <span class="pill warn">{counts['review']} prüfen</span>
                    <span class="pill bad">{counts['filtered']} gefiltert</span>
                    <span class="pill">{counts['imported']} importiert</span>
                  </p>
                  <p class="muted">Letzter Lauf: {esc(profile.get('last_run_at') or 'noch nie')}<br>{esc(profile.get('last_run_status') or '')}</p>
                  {error_html}
                  <details>
                    <summary><strong>Automatik einstellen</strong></summary>
                    <form method="post" action="search/profiles/{esc(pid)}/automation" data-loading="Automatik wird gespeichert …">
                      <div class="grid">
                        <div>
                          <label>Status</label>
                          <select name="enabled">
                            <option value="1" {_selected('1' if enabled else '0', '1')}>aktiv</option>
                            <option value="0" {_selected('1' if enabled else '0', '0')}>pausiert</option>
                          </select>
                        </div>
                        <div>
                          <label>Modus</label>
                          <select name="automation_mode">
                            <option value="manual" {_selected(mode, 'manual')}>nur manuell</option>
                            <option value="review" {_selected(mode, 'review')}>automatisch suchen, manuell importieren</option>
                            <option value="automatic" {_selected(mode, 'automatic')}>automatisch suchen und importieren</option>
                          </select>
                        </div>
                        <div><label>Intervall Minuten</label><input name="run_interval_minutes" type="number" min="15" max="1440" value="{esc(profile.get('run_interval_minutes') or 60)}"></div>
                        <div><label>Max. Treffer je Lauf</label><input name="max_results" type="number" min="10" max="160" value="{esc(profile.get('max_results') or 80)}"></div>
                        <div><label>Auto-Import ab Score</label><input name="auto_import_min_score" type="number" min="0" max="100" value="{esc(profile.get('auto_import_min_score') or 68)}"></div>
                        <div><label>Max. Auto-Importe je Lauf</label><input name="auto_import_limit_per_run" type="number" min="1" max="10" value="{esc(profile.get('auto_import_limit_per_run') or 2)}"></div>
                      </div>
                      <button type="submit">Automatik speichern</button>
                    </form>
                  </details>
                  <div class="top-actions">
                    <a class="button" href="search/profiles/{esc(pid)}">Kandidaten öffnen</a>
                    <form method="post" action="search/profiles/{esc(pid)}/run" data-loading="Willhaben wird durchsucht und passende Treffer werden verarbeitet …"><button class="secondary" type="submit">Jetzt ausführen</button></form>
                  </div>
                </div>
                """
            )

        body = f"""
        {PRODUCT_CSS}
        <div class="card">
          <h2>Willhaben-Suchprofil anlegen</h2>
          <p class="muted">Im Modus „automatisch suchen und importieren“ werden nur Kandidaten mit Status „neu“ und ausreichendem Vorab-Score als Hausakte angelegt. Medien, GitHub-Export und ChatGPT-Analyse starten danach automatisch.</p>
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
              <div><label>Automatikmodus</label><select name="automation_mode"><option value="manual">nur manuell</option><option value="review" selected>automatisch suchen, manuell importieren</option><option value="automatic">automatisch suchen und importieren</option></select></div>
              <div><label>Suchintervall Minuten</label><input name="run_interval_minutes" type="number" value="60" min="15" max="1440"></div>
              <div><label>Max. Treffer je Lauf</label><input name="max_results" type="number" value="80" min="10" max="160"></div>
              <div><label>Auto-Import ab Score</label><input name="auto_import_min_score" type="number" value="68" min="0" max="100"></div>
              <div><label>Max. Auto-Importe je Lauf</label><input name="auto_import_limit_per_run" type="number" value="2" min="1" max="10"></div>
            </div>
            <button type="submit">Suchprofil speichern</button>
          </form>
        </div>
        <h2>Gespeicherte Profile</h2>
        <div class="grid">{''.join(profile_cards) if profile_cards else '<div class="card muted">Noch keine Suchprofile gespeichert.</div>'}</div>
        """
        return layout("Automatische Suche", body, home_href="../")

    @app.post("/search/profiles")
    def create_profile_automatic(
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
        mode = automation_mode if automation_mode in {"manual", "review", "automatic"} else "review"
        profile_data: dict[str, Any] = {
            "name": name.strip(),
            "source_name": "willhaben.at",
            "max_price_eur": _as_int(max_price_eur),
            "soft_max_price_eur": _as_int(soft_max_price_eur),
            "min_living_area_m2": _as_float(min_living_area_m2),
            "min_plot_area_m2": _as_float(min_plot_area_m2),
            "regions": str(regions or "").strip(),
            "exclude_roads": exclude_roads,
            "hwb_warn": _as_float(hwb_warn),
            "hwb_reject": _as_float(hwb_reject),
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
        return RedirectResponse(f"profiles/{profile['id']}", status_code=303)

    @app.post("/search/profiles/{profile_id}/automation")
    def update_profile_automatic(
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
        return RedirectResponse("../../../search", status_code=303)

    @app.post("/search/profiles/{profile_id}/run")
    async def run_profile_automatic(profile_id: str) -> RedirectResponse:
        if not get_search_profile(profile_id):
            raise HTTPException(status_code=404, detail="Suchprofil nicht gefunden")
        try:
            await execute_profile_cycle(profile_id, force=True)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return RedirectResponse(f"../{profile_id}", status_code=303)
