from __future__ import annotations

import html as html_lib
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

import app.immoscout_support as support
import app.main as main
import app.modern_ui as modern_ui
import app.search_lifecycle_ui as lifecycle_ui
from app.search_automation import update_profile_automation
from app.storage import connect, get_search_profile, now_iso


_PATCHED = False
_ORIGINAL_RESOLVE_SEARCH_URLS = main.resolve_search_urls


def _methods(route: Any) -> set[str]:
    return set(getattr(route, "methods", set()) or set())


def _remove_route(app: FastAPI, path: str, method: str) -> None:
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (getattr(route, "path", "") == path and method in _methods(route))
    ]


def _number_text(value: object, fallback: float) -> str:
    try:
        number = float(value)
    except Exception:
        number = float(fallback)
    if number.is_integer():
        return str(int(number))
    return (f"{number:.2f}").rstrip("0").rstrip(".")


def parse_search_areas(value: object) -> list[str]:
    result: list[str] = []
    for token in re.split(r"[,;\s]+", str(value or "")):
        area = token.strip()
        if not re.fullmatch(r"[1-9][0-9]{3}", area):
            continue
        if area not in result:
            result.append(area)
    return result or ["8551"]


def build_immoscout_url_for_area(profile: dict[str, Any], area_id: str) -> str:
    max_price = profile.get("max_price_eur") or profile.get("soft_max_price_eur") or 420000
    min_living = profile.get("min_living_area_m2") or 120
    min_plot = profile.get("min_plot_area_m2") or 700
    params = [
        ("plotAreaFrom", _number_text(min_plot, 700)),
        ("primaryAreaFrom", _number_text(min_living, 120)),
        ("primaryPriceTo", _number_text(max_price, 420000)),
    ]
    return f"https://www.immobilienscout24.at/regional/{area_id}/haus-kaufen?{urlencode(params)}"


def build_immoscout_auto_urls(profile: dict[str, Any], area_ids: object | None = None) -> list[str]:
    return [build_immoscout_url_for_area(profile, area) for area in parse_search_areas(area_ids)]


def _split_urls(value: object) -> list[str]:
    return [item.strip() for item in re.split(r"[\n;]+", str(value or "")) if item.strip()]


def _is_standard_immoscout_url(url: str) -> bool:
    if not support.is_immoscout_url(url):
        return False
    parts = urlsplit(url)
    return bool(re.fullmatch(r"/regional/[1-9][0-9]{3}/haus-kaufen/?", parts.path, re.I))


def _is_standard_willhaben_url(url: str) -> bool:
    parts = urlsplit(url)
    if "willhaben.at" not in parts.netloc.lower():
        return False
    return "/iad/immobilien/haus-kaufen/haus-angebote" in parts.path and bool(dict(parse_qsl(parts.query)).get("areaId"))


def _is_auto_url(provider: str, url: str) -> bool:
    if provider == support.IMMOSCOUT_SOURCE:
        return _is_standard_immoscout_url(url)
    if provider == support.WILLHABEN_SOURCE:
        return _is_standard_willhaben_url(url)
    return False


def _areas_from_profile(profile: dict[str, Any]) -> list[str]:
    configured = parse_search_areas(profile.get("area_ids")) if str(profile.get("area_ids") or "").strip() else []
    if configured:
        return configured
    inferred: list[str] = []
    for url in _split_urls(profile.get("search_url")):
        match = re.search(r"/regional/([1-9][0-9]{3})/haus-kaufen", url, re.I)
        if not match:
            query_area = dict(parse_qsl(urlsplit(url).query)).get("areaId")
            match_value = str(query_area or "")
        else:
            match_value = match.group(1)
        if re.fullmatch(r"[1-9][0-9]{3}", match_value) and match_value not in inferred:
            inferred.append(match_value)
    return inferred or ["8551"]


def _custom_search_text(profile: dict[str, Any]) -> str:
    provider = str(profile.get("source_name") or support.WILLHABEN_SOURCE)
    urls = _split_urls(profile.get("search_url"))
    if urls and any(not _is_auto_url(provider, url) for url in urls):
        return "\n".join(urls)
    return ""


def resolve_search_urls_dynamic(profile: dict[str, Any]) -> list[str]:
    provider = str(profile.get("source_name") or support.WILLHABEN_SOURCE)
    urls = _split_urls(profile.get("search_url"))
    if urls and any(not _is_auto_url(provider, url) for url in urls):
        return urls
    areas = _areas_from_profile(profile)
    if provider == support.IMMOSCOUT_SOURCE:
        return build_immoscout_auto_urls(profile, areas)
    if provider == support.WILLHABEN_SOURCE:
        return main.build_willhaben_auto_urls(profile, areas)
    return _ORIGINAL_RESOLVE_SEARCH_URLS(profile)


def resolve_search_url_dynamic(profile: dict[str, Any]) -> str:
    return "\n".join(resolve_search_urls_dynamic(profile))


def validate_search_profile_url_dynamic(
    source_name: str,
    search_url: str,
    profile_data: dict[str, Any],
    area_ids: str | None,
) -> tuple[str, str]:
    provider = source_name if source_name in {support.WILLHABEN_SOURCE, support.IMMOSCOUT_SOURCE} else support.WILLHABEN_SOURCE
    urls = _split_urls(search_url)
    if urls:
        for url in urls:
            if not url.startswith(("http://", "https://")):
                raise HTTPException(status_code=400, detail="Ungültige Such-URL")
            detected = support.provider_for_url(url)
            if detected != provider:
                raise HTTPException(status_code=400, detail="Die eigene Such-URL passt nicht zum ausgewählten Portal")
        return provider, "\n".join(urls)
    if provider == support.IMMOSCOUT_SOURCE:
        return provider, "\n".join(build_immoscout_auto_urls(profile_data, area_ids))
    return provider, "\n".join(main.build_willhaben_auto_urls(profile_data, area_ids))


def _profile_form(profile: dict[str, Any] | None = None, action: str = "") -> str:
    profile = profile or {}
    provider = str(profile.get("source_name") or support.WILLHABEN_SOURCE)
    mode = str(profile.get("automation_mode") or "review")
    enabled = bool(int(profile.get("enabled") if profile.get("enabled") is not None else 1))
    custom_url = _custom_search_text(profile)

    def selected(current: str, value: str) -> str:
        return "selected" if current == value else ""

    return f"""
    <form method="post" action="{html_lib.escape(str(action or ''))}" data-loading="Suchprofil wird gespeichert …" data-dynamic-portal-search="true">
      <label>Name</label><input name="name" required value="{html_lib.escape(str(profile.get('name') or ''))}" placeholder="Familienhaus Südweststeiermark">
      <label>Portal</label>
      <select name="source_name">
        <option value="willhaben.at" {selected(provider, support.WILLHABEN_SOURCE)}>Willhaben</option>
        <option value="immobilienscout24.at" {selected(provider, support.IMMOSCOUT_SOURCE)}>ImmobilienScout24 Österreich</option>
      </select>
      <label>Regionen / Orte</label><input name="regions" value="{html_lib.escape(str(profile.get('regions') or 'Wies, Eibiswald, Oberhaag, Gleinstätten, Bad Schwanberg, Pölfing-Brunn, Frauental, Deutschlandsberg'))}">
      <label>PLZ / Suchgebiete</label><input name="area_ids" value="{html_lib.escape(str(profile.get('area_ids') or '8551,8552,8544,8553'))}" placeholder="z. B. 8551, 8552, 8544">
      <label>Eigene Such-URL optional</label><textarea name="search_url" rows="3" placeholder="Leer lassen = URL wird automatisch aus PLZ und Filtern erzeugt">{html_lib.escape(custom_url)}</textarea>
      <p class="muted">Ohne eigene URL erzeugt HausCheck je PLZ automatisch eine passende Portal-Suche.</p>
      <div class="notice" data-url-preview style="overflow-wrap:anywhere">Automatische Such-URL wird aus den Eingaben erzeugt.</div>
      <div class="grid" style="margin-top:12px">
        <div><label>Zielpreis bis €</label><input name="soft_max_price_eur" type="number" value="{html_lib.escape(str(profile.get('soft_max_price_eur') or 380000))}"></div>
        <div><label>Harte Grenze bis €</label><input name="max_price_eur" type="number" value="{html_lib.escape(str(profile.get('max_price_eur') or 420000))}"></div>
        <div><label>Mindestwohnfläche m²</label><input name="min_living_area_m2" type="number" step="0.1" value="{html_lib.escape(str(profile.get('min_living_area_m2') or 120))}"></div>
        <div><label>Wunsch-Grundstück m²</label><input name="min_plot_area_m2" type="number" step="0.1" value="{html_lib.escape(str(profile.get('min_plot_area_m2') or 700))}"></div>
        <div><label>HWB Warnung ab</label><input name="hwb_warn" type="number" step="0.1" value="{html_lib.escape(str(profile.get('hwb_warn') or 200))}"></div>
        <div><label>HWB kritisch ab</label><input name="hwb_reject" type="number" step="0.1" value="{html_lib.escape(str(profile.get('hwb_reject') or 300))}"></div>
      </div>
      <label>Ausschluss-/Prüfbegriffe</label><input name="exclude_roads" value="{html_lib.escape(str(profile.get('exclude_roads') or 'B76,B69,Bundesstraße,Hauptstraße'))}">
      <div class="grid">
        <div><label>Status</label><select name="enabled"><option value="1" {'selected' if enabled else ''}>aktiv</option><option value="0" {'selected' if not enabled else ''}>pausiert</option></select></div>
        <div><label>Ölheizung</label><select name="oil_policy"><option value="review" {selected(str(profile.get('oil_policy') or 'review'), 'review')}>prüfen</option><option value="reject" {selected(str(profile.get('oil_policy') or ''), 'reject')}>ausschließen</option><option value="allow" {selected(str(profile.get('oil_policy') or ''), 'allow')}>zulassen</option></select></div>
        <div><label>Modus</label><select name="automation_mode"><option value="manual" {selected(mode, 'manual')}>nur manuell</option><option value="review" {selected(mode, 'review')}>automatisch suchen, manuell importieren</option><option value="automatic" {selected(mode, 'automatic')}>automatisch suchen und importieren</option></select></div>
        <div><label>Intervall Minuten</label><input name="run_interval_minutes" type="number" min="15" max="1440" value="{html_lib.escape(str(profile.get('run_interval_minutes') or 60))}"></div>
        <div><label>Max. Treffer</label><input name="max_results" type="number" min="10" max="160" value="{html_lib.escape(str(profile.get('max_results') or 80))}"></div>
        <div><label>Auto-Import ab Score</label><input name="auto_import_min_score" type="number" min="0" max="100" value="{html_lib.escape(str(profile.get('auto_import_min_score') or 68))}"></div>
        <div><label>Max. Auto-Importe</label><input name="auto_import_limit_per_run" type="number" min="1" max="10" value="{html_lib.escape(str(profile.get('auto_import_limit_per_run') or 2))}"></div>
      </div>
      <button type="submit">Speichern</button>
    </form>
    <script>
    (() => {{
      const script = document.currentScript;
      const form = script && script.previousElementSibling;
      if (!form || !form.matches('[data-dynamic-portal-search]')) return;
      const field = name => form.querySelector(`[name="${{name}}"]`);
      const preview = form.querySelector('[data-url-preview]');
      const update = () => {{
        const custom = (field('search_url').value || '').trim();
        if (custom) {{ preview.textContent = 'Eigene Such-URL wird verwendet.'; return; }}
        const areas = (field('area_ids').value || '8551').split(/[;,\s]+/).filter(Boolean);
        const area = areas[0] || '8551';
        const maxPrice = field('max_price_eur').value || field('soft_max_price_eur').value || '420000';
        const living = field('min_living_area_m2').value || '120';
        const plot = field('min_plot_area_m2').value || '700';
        let url;
        if (field('source_name').value === 'immobilienscout24.at') {{
          url = `https://www.immobilienscout24.at/regional/${{encodeURIComponent(area)}}/haus-kaufen?plotAreaFrom=${{encodeURIComponent(plot)}}&primaryAreaFrom=${{encodeURIComponent(living)}}&primaryPriceTo=${{encodeURIComponent(maxPrice)}}`;
        }} else {{
          url = `https://www.willhaben.at/iad/immobilien/haus-kaufen/haus-angebote?areaId=${{encodeURIComponent(area)}}&page=1&PRICE_TO=${{encodeURIComponent(maxPrice)}}&ESTATE_SIZE/LIVING_AREA_FROM=${{encodeURIComponent(living)}}`;
        }}
        preview.textContent = `Automatisch: ${{url}}${{areas.length > 1 ? ` (+ ${{areas.length - 1}} weitere PLZ)` : ''}}`;
      }};
      form.addEventListener('input', update);
      form.addEventListener('change', update);
      update();
    }})();
    </script>
    """


def _profile_update_data(
    name: str,
    source_name: str,
    regions: str | None,
    area_ids: str | None,
    search_url: str | None,
    max_price_eur: str | None,
    soft_max_price_eur: str | None,
    min_living_area_m2: str | None,
    min_plot_area_m2: str | None,
    exclude_roads: str | None,
    hwb_warn: str | None,
    hwb_reject: str | None,
    oil_policy: str,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "name": name.strip(),
        "source_name": source_name,
        "max_price_eur": modern_ui.clean_int(max_price_eur),
        "soft_max_price_eur": modern_ui.clean_int(soft_max_price_eur),
        "min_living_area_m2": modern_ui.clean_float(min_living_area_m2),
        "min_plot_area_m2": modern_ui.clean_float(min_plot_area_m2),
        "regions": modern_ui.clean_text(regions),
        "exclude_roads": modern_ui.clean_text(exclude_roads),
        "hwb_warn": modern_ui.clean_float(hwb_warn),
        "hwb_reject": modern_ui.clean_float(hwb_reject),
        "oil_policy": oil_policy if oil_policy in {"review", "reject", "allow"} else "review",
    }
    provider, resolved = validate_search_profile_url_dynamic(source_name, str(search_url or ""), data, area_ids)
    data["source_name"] = provider
    data["search_url"] = resolved
    return data


def _profile_card(profile: dict[str, Any]) -> str:
    original = support._ORIGINAL_PROFILE_CARD
    if not original:
        return ""
    html = original(profile)
    provider = str(profile.get("source_name") or support.WILLHABEN_SOURCE)
    label = "ImmobilienScout24" if provider == support.IMMOSCOUT_SOURCE else "Willhaben"
    urls = resolve_search_urls_dynamic(profile)
    summary = f'<p class="muted"><strong>Portal:</strong> {label}'
    if urls:
        summary += f'<br><span style="overflow-wrap:anywhere">{html_lib.escape(urls[0])}</span>'
        if len(urls) > 1:
            summary += f'<br>+ {len(urls) - 1} weitere PLZ-Suche(n)'
    summary += "</p>"
    return html.replace("<p>", summary + "<p>", 1)


def _register_edit_routes(app: FastAPI) -> None:
    _remove_route(app, "/settings/search/{profile_id}/edit", "GET")
    _remove_route(app, "/settings/search/{profile_id}/edit", "POST")

    @app.get("/settings/search/{profile_id}/edit", response_class=HTMLResponse)
    def edit_profile_page(profile_id: str) -> HTMLResponse:
        profile = get_search_profile(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Suchprofil nicht gefunden")
        body = (
            '<div class="page-heading"><div><h1>Suchprofil bearbeiten</h1>'
            '<p>Portal, PLZ, Filter und Automatikwerte können geändert werden. Die Portal-URL wird automatisch neu erzeugt.</p>'
            f'</div><a class="button ghost" href="../../search">{modern_ui.icon("back")} Zurück</a></div>'
            f'<div class="card">{_profile_form(profile, "")}</div>'
        )
        return modern_ui.modern_layout("Suchprofil bearbeiten", body, home_href="../../../../")

    @app.post("/settings/search/{profile_id}/edit")
    async def edit_profile_route(
        profile_id: str,
        name: str = Form(...),
        source_name: str | None = Form(None),
        regions: str | None = Form(None),
        area_ids: str | None = Form(None),
        search_url: str | None = Form(None),
        max_price_eur: str | None = Form(None),
        soft_max_price_eur: str | None = Form(None),
        min_living_area_m2: str | None = Form(None),
        min_plot_area_m2: str | None = Form(None),
        exclude_roads: str | None = Form(None),
        hwb_warn: str | None = Form(None),
        hwb_reject: str | None = Form(None),
        oil_policy: str = Form("review"),
        enabled: int = Form(1),
        automation_mode: str = Form("review"),
        run_interval_minutes: int = Form(60),
        max_results: int = Form(80),
        auto_import_min_score: int = Form(68),
        auto_import_limit_per_run: int = Form(2),
    ) -> RedirectResponse:
        current = get_search_profile(profile_id)
        if not current:
            raise HTTPException(status_code=404, detail="Suchprofil nicht gefunden")
        selected_provider = source_name or str(current.get("source_name") or support.WILLHABEN_SOURCE)
        data = _profile_update_data(
            name,
            selected_provider,
            regions,
            area_ids,
            search_url,
            max_price_eur,
            soft_max_price_eur,
            min_living_area_m2,
            min_plot_area_m2,
            exclude_roads,
            hwb_warn,
            hwb_reject,
            oil_policy,
        )
        data["updated_at"] = now_iso()
        with connect() as con:
            sql = ", ".join(f"{key} = ?" for key in data)
            con.execute(f"UPDATE search_profiles SET {sql} WHERE id = ?", list(data.values()) + [profile_id])
            con.commit()
        mode = automation_mode if automation_mode in {"manual", "review", "automatic"} else "review"
        update_profile_automation(
            profile_id,
            {
                "enabled": 1 if enabled else 0,
                "area_ids": ",".join(parse_search_areas(area_ids)),
                "automation_mode": mode,
                "run_interval_minutes": max(15, min(int(run_interval_minutes), 1440)),
                "auto_import_enabled": 1 if mode == "automatic" else 0,
                "max_results": max(10, min(int(max_results), 160)),
                "auto_import_min_score": max(0, min(int(auto_import_min_score), 100)),
                "auto_import_limit_per_run": max(1, min(int(auto_import_limit_per_run), 10)),
                "last_run_status": "Einstellungen aktualisiert · Such-URL neu erzeugt" if not str(search_url or "").strip() else "Einstellungen aktualisiert · eigene Such-URL",
                "last_error": None,
            },
        )
        return RedirectResponse("../../search", status_code=303)


def register_immoscout_dynamic_search(app: FastAPI) -> None:
    global _PATCHED
    if _PATCHED:
        return

    support._validate_search_profile_url = validate_search_profile_url_dynamic
    support._profile_form_html = lambda: _profile_form(None, "profiles")
    main.resolve_search_urls = resolve_search_urls_dynamic
    main.resolve_search_url = resolve_search_url_dynamic
    modern_ui._profile_form = _profile_form
    lifecycle_ui._new_profile_form = lambda: _profile_form(None, "profiles")
    lifecycle_ui._profile_card = _profile_card

    # Die Support-Routen werden mit der neuen dynamischen URL-Auflösung erneut registriert.
    support._register_profile_routes(app)
    _register_edit_routes(app)
    _PATCHED = True
