from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

import app.dashboard_automation_ui as dashboard_automation_ui
import app.focused_ui as focused_ui
import app.main as main
import app.product_ui as product_ui
import app.search_automation_ui as search_automation_ui
import app.search_lifecycle_ui as search_lifecycle_ui
from app.github_auto_export import auto_export_house_to_github
from app.house_manage import clean_float, clean_int, clean_text, update_house_details
from app.house_merge import preview_for_dashboard, set_preview_media
from app.pipeline_status import get_pipeline_status, set_pipeline_stage
from app.search_automation import update_profile_automation
from app.storage import (
    add_evidence,
    add_media,
    connect,
    ensure_columns,
    get_house,
    get_media,
    get_search_profile,
    list_houses,
    list_media,
    list_search_profiles,
    list_sources,
    now_iso,
    project_dir,
    row_to_dict,
)
from app.ui_helpers import esc, format_datetime, house_score_html, house_score_result


MODERN_CSS = r"""
<style>
:root {
  color-scheme: dark;
  --bg: #0a0f14;
  --surface: #111820;
  --surface-2: #17212b;
  --surface-3: #1d2935;
  --border: #263746;
  --text: #f4f7f9;
  --muted: #9eacb8;
  --primary: #4da3ff;
  --primary-strong: #2f80ed;
  --success: #42b883;
  --warning: #e6a94f;
  --danger: #e06c75;
  --radius-sm: 10px;
  --radius: 16px;
  --radius-lg: 24px;
  --shadow: 0 12px 36px rgba(0,0,0,.24);
  --content: 1180px;
}
html { background: var(--bg); }
body { margin:0; background:linear-gradient(180deg,#0d141b 0,#0a0f14 260px); color:var(--text); font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; line-height:1.5; }
* { box-sizing:border-box; }
a { color:var(--primary); }
.app-header { position:sticky; top:0; z-index:100; background:rgba(10,15,20,.88); backdrop-filter:blur(18px); border-bottom:1px solid rgba(255,255,255,.07); }
.app-header-inner { max-width:var(--content); min-height:64px; margin:0 auto; padding:0 20px; display:flex; align-items:center; gap:14px; }
.app-brand { display:flex; align-items:center; gap:10px; color:var(--text); text-decoration:none; font-weight:800; letter-spacing:-.02em; }
.app-brand-mark { width:34px; height:34px; display:grid; place-items:center; border-radius:11px; background:linear-gradient(145deg,#4da3ff,#2f80ed); box-shadow:0 8px 24px rgba(47,128,237,.3); }
.app-title { margin-left:auto; color:var(--muted); font-size:14px; font-weight:650; max-width:48%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.app-main { width:min(var(--content),100%); margin:0 auto; padding:24px 20px 96px; }
.bottom-nav { display:none; }
.page-heading { display:flex; justify-content:space-between; align-items:flex-end; gap:16px; margin:6px 0 20px; }
.page-heading h1 { margin:0; font-size:clamp(26px,4vw,38px); line-height:1.08; letter-spacing:-.035em; }
.page-heading p { margin:6px 0 0; color:var(--muted); }
.page-actions,.action-row { display:flex; flex-wrap:wrap; gap:9px; align-items:center; }
.card { background:linear-gradient(180deg,rgba(23,33,43,.97),rgba(17,24,32,.97)); border:1px solid var(--border); border-radius:var(--radius); padding:18px; box-shadow:none; }
.card:hover { border-color:#32495c; }
.card h2,.card h3 { margin-top:0; letter-spacing:-.015em; }
.section { margin-top:18px; }
.section-title { display:flex; align-items:center; justify-content:space-between; gap:12px; margin:26px 0 12px; }
.section-title h2 { margin:0; font-size:21px; letter-spacing:-.02em; }
.muted { color:var(--muted)!important; }
.subtle { color:#c4ced6; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:14px; }
.two-column { display:grid; grid-template-columns:minmax(0,1.45fr) minmax(300px,.75fr); gap:16px; align-items:start; }
.button,button { appearance:none; border:1px solid transparent; border-radius:12px; padding:10px 14px; min-height:42px; background:var(--primary-strong); color:#fff; font:inherit; font-weight:750; text-decoration:none; display:inline-flex; align-items:center; justify-content:center; gap:8px; cursor:pointer; margin:0; transition:transform .15s ease,background .15s ease,border-color .15s ease; }
.button:hover,button:hover { transform:translateY(-1px); }
.button.secondary,button.secondary { background:var(--surface-3); border-color:#344758; color:var(--text); }
.button.ghost,button.ghost { background:transparent; border-color:var(--border); color:var(--text); }
.button.danger,button.danger { background:#4b2328; border-color:#77343c; color:#ffdfe3; }
.icon-button { width:42px!important; height:42px!important; min-width:42px!important; padding:0!important; border-radius:12px!important; display:inline-grid!important; place-items:center; background:var(--surface-3)!important; border:1px solid var(--border)!important; color:var(--text)!important; }
.icon-button svg,.button svg,button svg { width:19px; height:19px; flex:none; }
.pill { display:inline-flex; align-items:center; gap:5px; padding:5px 9px; border-radius:999px; background:#22303d; color:#dbe4ea; margin:2px 4px 2px 0; font-size:12px; font-weight:650; }
.pill.good { background:#174633; color:#c9f7df; }
.pill.warn { background:#5a421d; color:#ffe9bd; }
.pill.bad { background:#56282d; color:#ffd8dc; }
input,textarea,select { width:100%; padding:11px 12px; margin:6px 0 14px; border:1px solid #344758; border-radius:12px; background:#0d141b; color:var(--text); font:inherit; font-size:16px; outline:none; }
input:focus,textarea:focus,select:focus { border-color:var(--primary); box-shadow:0 0 0 3px rgba(77,163,255,.14); }
label { display:block; color:#d8e0e6; font-size:13px; font-weight:700; }
summary { cursor:pointer; list-style:none; }
summary::-webkit-details-marker { display:none; }
details>summary { display:flex; align-items:center; justify-content:space-between; gap:12px; min-height:42px; }
details>summary:after { content:"⌄"; color:var(--muted); font-size:18px; }
table { width:100%; border-collapse:collapse; overflow-x:auto; }
th,td { padding:10px; border-bottom:1px solid var(--border); text-align:left; vertical-align:top; }
.hero { position:relative; min-height:300px; border-radius:var(--radius-lg); overflow:hidden; background:#0c1218; border:1px solid var(--border); box-shadow:var(--shadow); }
.hero img { width:100%; height:clamp(300px,48vw,540px); display:block; object-fit:cover; }
.hero-overlay { position:absolute; inset:auto 0 0; padding:70px 22px 20px; background:linear-gradient(transparent,rgba(5,8,12,.9)); }
.hero-overlay h1 { margin:0; font-size:clamp(25px,4vw,42px); line-height:1.08; letter-spacing:-.035em; text-shadow:0 2px 14px rgba(0,0,0,.5); }
.hero-overlay p { margin:7px 0 0; color:#d4dde3; }
.detail-toolbar { position:sticky; top:76px; z-index:50; margin:12px 0 18px; padding:9px; background:rgba(17,24,32,.92); backdrop-filter:blur(16px); border:1px solid var(--border); border-radius:15px; display:flex; gap:8px; overflow-x:auto; box-shadow:0 8px 26px rgba(0,0,0,.18); }
.detail-toolbar form { margin:0; }
.detail-toolbar .button,.detail-toolbar button { white-space:nowrap; }
.facts-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(135px,1fr)); gap:10px; }
.fact { padding:13px; background:#0e161e; border:1px solid #243542; border-radius:13px; }
.fact-label { color:var(--muted); font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.045em; }
.fact-value { margin-top:3px; font-size:18px; font-weight:800; }
.house-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(270px,1fr)); gap:16px; }
.house-card { padding:0!important; overflow:hidden; position:relative; transition:transform .18s ease,border-color .18s ease; }
.house-card:hover { transform:translateY(-2px); border-color:#3c5870; }
.house-card-media { position:relative; display:block; aspect-ratio:16/10; overflow:hidden; background:#0c1218; }
.house-card-media img { width:100%; height:100%; object-fit:cover; display:block; transition:transform .25s ease; }
.house-card:hover .house-card-media img { transform:scale(1.025); }
.house-card-content { padding:15px; }
.house-card h3 { margin:0 0 5px; font-size:18px; line-height:1.25; }
.house-card-title { color:var(--text); text-decoration:none; }
.house-card-actions { display:flex; gap:8px; margin-top:12px; }
.house-card-actions .button { flex:1; }
.dashboard-banner { display:flex; align-items:center; justify-content:space-between; gap:14px; margin:0 0 18px; background:linear-gradient(135deg,#173451,#162535); }
.dashboard-banner strong { font-size:18px; }
.gallery-clean { display:grid; grid-template-columns:repeat(auto-fill,minmax(170px,1fr)); gap:10px; }
.gallery-clean a { display:block; aspect-ratio:4/3; border-radius:13px; overflow:hidden; background:#0b1117; border:1px solid var(--border); }
.gallery-clean img { width:100%; height:100%; object-fit:cover; display:block; transition:transform .2s ease; }
.gallery-clean a:hover img { transform:scale(1.03); }
.cover-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(190px,1fr)); gap:12px; }
.cover-choice { position:relative; overflow:hidden; border:2px solid transparent; border-radius:15px; background:#0d141b; }
.cover-choice.selected { border-color:var(--success); box-shadow:0 0 0 3px rgba(66,184,131,.12); }
.cover-choice img { width:100%; aspect-ratio:4/3; object-fit:cover; display:block; }
.cover-choice form { position:absolute; inset:8px 8px auto auto; }
.cover-choice button { width:40px; height:40px; min-height:40px; padding:0; border-radius:50%; background:rgba(8,13,18,.78); border:1px solid rgba(255,255,255,.22); backdrop-filter:blur(8px); }
.cover-choice.selected button { background:var(--success); }
.merge-list { display:grid; gap:10px; }
.merge-option { display:grid; grid-template-columns:22px 92px 1fr; gap:12px; align-items:center; padding:10px; border:1px solid var(--border); border-radius:14px; background:#0d141b; cursor:pointer; }
.merge-option:has(input:checked) { border-color:var(--primary); box-shadow:0 0 0 3px rgba(77,163,255,.12); }
.merge-option input { width:auto; margin:0; }
.merge-option img { width:92px; height:68px; object-fit:cover; border-radius:10px; }
.source-card { padding:13px; border:1px solid var(--border); border-radius:13px; background:#0d141b; }
.empty-state { padding:34px 20px; text-align:center; }
.notice { padding:12px 14px; border-radius:13px; border:1px solid #315170; background:#13293e; color:#d6ebff; }
.notice.warning { border-color:#6d542e; background:#352817; color:#ffe9bf; }
.danger-zone { border-color:#5c3035!important; }
.loading-overlay { position:fixed; inset:0; z-index:9999; display:none; align-items:center; justify-content:center; background:rgba(5,8,12,.78); backdrop-filter:blur(5px); padding:20px; }
.loading-overlay.active { display:flex; }
.loading-box { width:min(380px,100%); background:var(--surface); border:1px solid var(--border); border-radius:20px; padding:24px; text-align:center; box-shadow:var(--shadow); }
.spinner { width:42px; height:42px; margin:0 auto 14px; border-radius:50%; border:4px solid #344758; border-top-color:var(--primary); animation:spin .8s linear infinite; }
@keyframes spin { to { transform:rotate(360deg); } }
@media (max-width:820px) {
  .app-main { padding:18px 13px 94px; }
  .app-header-inner { padding:0 14px; }
  .two-column { grid-template-columns:1fr; }
  .page-heading { align-items:flex-start; }
  .page-actions { width:100%; }
  .detail-toolbar { top:68px; margin-left:-4px; margin-right:-4px; }
  .bottom-nav { position:fixed; display:grid; grid-template-columns:repeat(4,1fr); left:10px; right:10px; bottom:10px; z-index:200; padding:7px; border:1px solid var(--border); border-radius:18px; background:rgba(17,24,32,.94); backdrop-filter:blur(18px); box-shadow:0 12px 38px rgba(0,0,0,.4); }
  .bottom-nav a { min-height:48px; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:2px; color:var(--muted); text-decoration:none; font-size:10px; font-weight:700; border-radius:12px; }
  .bottom-nav a svg { width:20px; height:20px; }
  .bottom-nav a:hover { background:var(--surface-3); color:var(--text); }
  .hero { min-height:245px; border-radius:18px; }
  .hero img { height:310px; }
  .dashboard-banner { align-items:flex-start; flex-direction:column; }
}
@media (max-width:520px) {
  .house-grid { grid-template-columns:1fr; }
  .page-heading { display:block; }
  .page-heading .page-actions { margin-top:12px; }
  .detail-toolbar .button,.detail-toolbar button { padding:9px 11px; }
  .cover-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .merge-option { grid-template-columns:22px 72px 1fr; }
  .merge-option img { width:72px; height:58px; }
}
</style>
"""


def icon(name: str) -> str:
    paths = {
        "home": '<path d="M3 11.5 12 4l9 7.5"/><path d="M5 10.5V20h14v-9.5"/><path d="M9 20v-6h6v6"/>',
        "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
        "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21H10v-.1A1.7 1.7 0 0 0 8.6 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H3V10h.1A1.7 1.7 0 0 0 4.6 8.6a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V3H14v.1A1.7 1.7 0 0 0 15.4 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19.4 9c.17.37.48.7.86.9.33.17.7.26 1.07.26H21v3.68h-.1A1.7 1.7 0 0 0 19.4 15Z"/>',
        "trash": '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="m7 7 1 13h8l1-13"/><path d="M10 11v5M14 11v5"/>',
        "plus": '<path d="M12 5v14M5 12h14"/>',
        "refresh": '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
        "merge": '<path d="M6 3v4a5 5 0 0 0 5 5h7"/><path d="m15 9 3 3-3 3"/><path d="M6 21v-4a5 5 0 0 1 5-5"/>',
        "image": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9" r="1.5"/><path d="m21 15-5-5L5 20"/>',
        "edit": '<path d="M4 20h4l11-11-4-4L4 16v4Z"/><path d="m13.5 6.5 4 4"/>',
        "external": '<path d="M14 4h6v6"/><path d="M10 14 20 4"/><path d="M20 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h5"/>',
        "back": '<path d="m15 18-6-6 6-6"/>',
        "check": '<path d="m5 12 4 4L19 6"/>',
    }
    return f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{paths.get(name, paths["home"])}</svg>'


def modern_layout(title: str, body: str, home_href: str = "./") -> HTMLResponse:
    base = home_href if home_href.endswith("/") else home_href + "/"
    return HTMLResponse(
        f"""
<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
  <meta name="theme-color" content="#0a0f14">
  <title>{esc(title)} · HausCheck</title>
  {MODERN_CSS}
</head>
<body>
  <header class="app-header">
    <div class="app-header-inner">
      <a class="app-brand" href="{esc(home_href)}"><span class="app-brand-mark">{icon('home')}</span><span>HausCheck</span></a>
      <div class="app-title">{esc(title)}</div>
    </div>
  </header>
  <main class="app-main">{body}</main>
  <nav class="bottom-nav" aria-label="Hauptnavigation">
    <a href="{esc(home_href)}">{icon('home')}<span>Hausakten</span></a>
    <a href="{esc(base + 'search')}">{icon('search')}<span>Suche</span></a>
    <a href="{esc(base + 'rejected')}">{icon('trash')}<span>Abgelehnt</span></a>
    <a href="{esc(base + 'settings')}">{icon('settings')}<span>Einstellungen</span></a>
  </nav>
  <div id="loading-overlay" class="loading-overlay"><div class="loading-box"><div class="spinner"></div><strong id="loading-title">Bitte warten …</strong><p id="loading-text" class="muted">Die Aktion wird ausgeführt.</p></div></div>
  <script>
  (() => {{
    const overlay=document.getElementById('loading-overlay');
    document.querySelectorAll('form[data-loading]').forEach(form=>{{
      form.addEventListener('submit',()=>{{
        const message=form.getAttribute('data-loading')||'Bitte warten …';
        document.getElementById('loading-title').textContent=message;
        overlay.classList.add('active');
        form.querySelectorAll('button').forEach(button=>button.disabled=true);
      }});
    }});
  }})();
  </script>
</body>
</html>
"""
    )


def _remove_route(app: FastAPI, path: str, method: str) -> None:
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (getattr(route, "path", "") == path and method in set(getattr(route, "methods", set()) or set()))
    ]


def ensure_modern_schema() -> None:
    with connect() as con:
        ensure_columns(
            con,
            "houses",
            {
                "last_refreshed_at": "TEXT",
                "last_refresh_summary": "TEXT",
            },
        )
        con.commit()


def _active_houses() -> list[dict[str, Any]]:
    return [house for house in list_houses() if str(house.get("status") or "new") != "rejected"]


def _candidate_count() -> int:
    with connect() as con:
        row = con.execute(
            """
            SELECT COUNT(*) FROM search_candidates
            WHERE imported_house_id IS NULL
              AND status IN ('new','review','changed','reactivated')
            """
        ).fetchone()
    return int(row[0] or 0) if row else 0


def _house_images(house_id: str) -> list[dict[str, Any]]:
    house = get_house(house_id) or {}
    selected = str(house.get("preview_media_id") or "")
    images = [
        item for item in list_media(house_id)
        if item.get("kind") == "image" and item.get("download_status") == "downloaded" and item.get("local_path")
    ]
    images.sort(key=lambda item: (0 if str(item.get("id") or "") == selected else 1, str(item.get("created_at") or "")))
    return images


def _hero_image(house: dict[str, Any]) -> str:
    images = _house_images(str(house.get("id") or ""))
    if images:
        return f'../media/{esc(images[0].get("id"))}'
    preview = str(house.get("preview_image_url") or "").strip()
    return esc(preview) if preview else ""


def _house_card(house: dict[str, Any]) -> str:
    house_id = str(house.get("id") or "")
    score = house_score_result(house)
    status = get_pipeline_status(house_id)
    preview = preview_for_dashboard(house)
    return f"""
    <article class="card house-card">
      <a class="house-card-media" href="houses/{esc(house_id)}">{preview}</a>
      <div class="house-card-content">
        <a class="house-card-title" href="houses/{esc(house_id)}"><h3>{esc(house.get('title'))}</h3></a>
        <div class="muted">{esc(house.get('location_text') or 'Lage unbekannt')}</div>
        <p><span class="pill {esc(score.get('pill'))}">{'KI' if score.get('source') == 'ai' else 'Vorprüfung'} {esc(score.get('score'))}/100</span>{product_ui._pipeline_badge(status)}</p>
        <p><span class="pill">{main.money(house.get('price_eur'))}</span><span class="pill">{main.num(house.get('living_area_m2'),' m²')}</span><span class="pill">{main.num(house.get('plot_area_m2'),' m² Grund')}</span></p>
        <div class="house-card-actions">
          <a class="button secondary" href="houses/{esc(house_id)}">Hausakte öffnen</a>
          <form method="post" action="houses/{esc(house_id)}/reject" data-no-loading="true" onsubmit="return confirm('Dieses Objekt als abgelehnt markieren?');"><button class="icon-button" type="submit" title="Ablehnen" aria-label="Ablehnen">{icon('trash')}</button></form>
        </div>
      </div>
    </article>
    """


def _facts_html(house: dict[str, Any]) -> str:
    facts = [
        ("Kaufpreis", main.money(house.get("price_eur"))),
        ("Wohnfläche", main.num(house.get("living_area_m2"), " m²")),
        ("Grundstück", main.num(house.get("plot_area_m2"), " m²")),
        ("Zimmer", main.num(house.get("rooms"))),
        ("Baujahr", main.num(house.get("year_built"))),
        ("HWB", main.num(house.get("energy_hwb"))),
        ("fGEE", main.num(house.get("energy_fgee"))),
        ("Heizung", esc(house.get("heating") or "unbekannt")),
    ]
    return '<div class="facts-grid">' + ''.join(f'<div class="fact"><div class="fact-label">{esc(label)}</div><div class="fact-value">{value}</div></div>' for label,value in facts) + '</div>'


def _gallery_html(house_id: str) -> str:
    images = _house_images(house_id)
    if not images:
        return '<div class="card empty-state"><p class="muted">Noch keine Bilder vorhanden.</p></div>'
    return '<div class="gallery-clean">' + ''.join(
        f'<a href="../media/{esc(item.get("id"))}" target="_blank"><img src="../media/{esc(item.get("id"))}" alt="Hausbild"></a>'
        for item in images
    ) + '</div>'


def _sources_html(house_id: str) -> str:
    sources = list_sources(house_id)
    if not sources:
        return '<p class="muted">Keine Inseratsquelle gespeichert.</p>'
    cards = []
    for index, source in enumerate(reversed(sources), start=1):
        url = str(source.get("source_url") or "")
        cards.append(
            f"""
            <div class="source-card">
              <strong>Inserat {index}: {esc(source.get('source_name') or 'Quelle')}</strong>
              <p class="muted">ID {esc(source.get('external_id') or '–')} · zuletzt gelesen {esc(format_datetime(source.get('updated_at')))}</p>
              <a class="button ghost" href="{esc(url)}" target="_blank">{icon('external')} Inserat öffnen</a>
            </div>
            """
        )
    return '<div class="grid">' + ''.join(cards) + '</div>'


def _profile_form(profile: dict[str, Any] | None = None, action: str = "") -> str:
    profile = profile or {}
    mode = str(profile.get("automation_mode") or "review")
    enabled = bool(int(profile.get("enabled") if profile.get("enabled") is not None else 1))
    def selected(value: str) -> str:
        return "selected" if mode == value else ""
    return f"""
    <form method="post" action="{esc(action)}" data-loading="Suchprofil wird gespeichert …">
      <label>Name</label><input name="name" required value="{esc(profile.get('name') or '')}" placeholder="Familienhaus Südweststeiermark">
      <label>Regionen / Orte</label><input name="regions" value="{esc(profile.get('regions') or 'Wies, Eibiswald, Oberhaag, Gleinstätten, Bad Schwanberg, Pölfing-Brunn, Frauental, Deutschlandsberg')}">
      <label>Willhaben PLZ / areaIds</label><input name="area_ids" value="{esc(profile.get('area_ids') or '8551,8552,8544,8553')}">
      <label>Eigene Willhaben-Such-URL optional</label><textarea name="search_url" rows="3" placeholder="Leer lassen = URL wird aus den Filtern erzeugt">{esc(profile.get('search_url') or '')}</textarea>
      <div class="grid">
        <div><label>Zielpreis bis €</label><input name="soft_max_price_eur" type="number" value="{esc(profile.get('soft_max_price_eur') or 380000)}"></div>
        <div><label>Harte Grenze bis €</label><input name="max_price_eur" type="number" value="{esc(profile.get('max_price_eur') or 400000)}"></div>
        <div><label>Mindestwohnfläche m²</label><input name="min_living_area_m2" type="number" step="0.1" value="{esc(profile.get('min_living_area_m2') or 120)}"></div>
        <div><label>Wunsch-Grundstück m²</label><input name="min_plot_area_m2" type="number" step="0.1" value="{esc(profile.get('min_plot_area_m2') or 700)}"></div>
        <div><label>HWB Warnung ab</label><input name="hwb_warn" type="number" step="0.1" value="{esc(profile.get('hwb_warn') or 200)}"></div>
        <div><label>HWB kritisch ab</label><input name="hwb_reject" type="number" step="0.1" value="{esc(profile.get('hwb_reject') or 300)}"></div>
      </div>
      <label>Ausschluss-/Prüfbegriffe</label><input name="exclude_roads" value="{esc(profile.get('exclude_roads') or 'B76,B69,Bundesstraße,Hauptstraße')}">
      <div class="grid">
        <div><label>Status</label><select name="enabled"><option value="1" {'selected' if enabled else ''}>aktiv</option><option value="0" {'selected' if not enabled else ''}>pausiert</option></select></div>
        <div><label>Ölheizung</label><select name="oil_policy"><option value="review" {'selected' if profile.get('oil_policy','review') == 'review' else ''}>prüfen</option><option value="reject" {'selected' if profile.get('oil_policy') == 'reject' else ''}>ausschließen</option><option value="allow" {'selected' if profile.get('oil_policy') == 'allow' else ''}>zulassen</option></select></div>
        <div><label>Modus</label><select name="automation_mode"><option value="manual" {selected('manual')}>nur manuell</option><option value="review" {selected('review')}>automatisch suchen, manuell importieren</option><option value="automatic" {selected('automatic')}>automatisch suchen und importieren</option></select></div>
        <div><label>Intervall Minuten</label><input name="run_interval_minutes" type="number" min="15" max="1440" value="{esc(profile.get('run_interval_minutes') or 60)}"></div>
        <div><label>Max. Treffer</label><input name="max_results" type="number" min="10" max="160" value="{esc(profile.get('max_results') or 80)}"></div>
        <div><label>Auto-Import ab Score</label><input name="auto_import_min_score" type="number" min="0" max="100" value="{esc(profile.get('auto_import_min_score') or 68)}"></div>
        <div><label>Max. Auto-Importe</label><input name="auto_import_limit_per_run" type="number" min="1" max="10" value="{esc(profile.get('auto_import_limit_per_run') or 2)}"></div>
      </div>
      <button type="submit">Speichern</button>
    </form>
    """


def _profile_update_data(
    name: str,
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
    data = {
        "name": name.strip(),
        "source_name": "willhaben.at",
        "max_price_eur": clean_int(max_price_eur),
        "soft_max_price_eur": clean_int(soft_max_price_eur),
        "min_living_area_m2": clean_float(min_living_area_m2),
        "min_plot_area_m2": clean_float(min_plot_area_m2),
        "regions": clean_text(regions),
        "exclude_roads": clean_text(exclude_roads),
        "hwb_warn": clean_float(hwb_warn),
        "hwb_reject": clean_float(hwb_reject),
        "oil_policy": oil_policy if oil_policy in {"review","reject","allow"} else "review",
    }
    raw_url = str(search_url or "").strip()
    if raw_url:
        urls = [line.strip() for line in raw_url.splitlines() if line.strip()]
        if any(not url.startswith(("http://","https://")) or "willhaben.at" not in url.lower() for url in urls):
            raise ValueError("Es sind nur gültige Willhaben-Such-URLs erlaubt")
        data["search_url"] = "\n".join(urls)
    else:
        data["search_url"] = "\n".join(main.build_willhaben_auto_urls(data, area_ids))
    return data


def _parsed_value(parsed: Any, field: str) -> Any:
    return getattr(parsed, field, None)


def _choose_value(parsed_items: list[Any], field: str, current: Any) -> Any:
    values = [_parsed_value(parsed, field) for parsed in parsed_items]
    values = [value for value in values if value not in (None, "", "unknown")]
    if not values:
        return current
    if field == "price_eur":
        try:
            return int(min(float(value) for value in values))
        except Exception:
            return values[0]
    normalized = [str(value) for value in values]
    most_common = Counter(normalized).most_common(1)[0][0]
    for value in values:
        if str(value) == most_common:
            return value
    return values[0]


async def refresh_house_from_sources(house_id: str) -> dict[str, Any]:
    ensure_modern_schema()
    house = get_house(house_id)
    if not house:
        raise ValueError("Hausakte nicht gefunden")
    with connect() as con:
        source_rows = [row_to_dict(row) or {} for row in con.execute(
            "SELECT * FROM listing_sources WHERE house_id = ? ORDER BY created_at ASC",
            (house_id,),
        ).fetchall()]
    web_sources = [source for source in source_rows if str(source.get("source_url") or "").startswith(("http://","https://"))]
    if not web_sources:
        raise ValueError("Diese Hausakte besitzt keine aktualisierbare Inseratsquelle")

    before = {key: house.get(key) for key in ["title","location_text","price_eur","living_area_m2","plot_area_m2","rooms","year_built","heating","energy_hwb","energy_fgee"]}
    media_before = len(list_media(house_id))
    parsed_items: list[Any] = []
    errors: list[str] = []
    set_pipeline_stage(house_id, "refreshing", "running", "Inseratsquellen, Daten und Medien werden aktualisiert.")

    for source in web_sources:
        source_id = str(source.get("id") or "")
        source_url = str(source.get("source_url") or "")
        try:
            raw_html = await main.fetch_html(source_url)
            parsed = main.parse_listing(source_url, raw_html)
            parsed_items.append(parsed)
            html_path = project_dir(house_id) / "html" / f"source_{source_id}.html"
            html_path.write_text(raw_html, encoding="utf-8")
            with connect() as con:
                con.execute(
                    """
                    UPDATE listing_sources
                    SET source_name = ?, external_id = ?, description = ?, raw_html_path = ?,
                        parser_status = ?, parser_warnings = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        parsed.source_name,
                        parsed.external_id,
                        parsed.description,
                        str(html_path),
                        "success" if not parsed.warnings else "partial",
                        json.dumps(parsed.warnings, ensure_ascii=False),
                        now_iso(),
                        source_id,
                    ),
                )
                con.execute("DELETE FROM field_evidence WHERE source_id = ?", (source_id,))
                con.execute(
                    """
                    UPDATE search_candidates
                    SET title = COALESCE(?, title), price_eur = COALESCE(?, price_eur),
                        living_area_m2 = COALESCE(?, living_area_m2), plot_area_m2 = COALESCE(?, plot_area_m2),
                        energy_hwb = COALESCE(?, energy_hwb), preview_image_url = COALESCE(?, preview_image_url),
                        last_seen_at = ?, status = CASE WHEN imported_house_id IS NOT NULL THEN 'imported' ELSE status END
                    WHERE source_url = ? OR (? IS NOT NULL AND external_id = ?)
                    """,
                    (
                        parsed.title,
                        parsed.price_eur,
                        parsed.living_area_m2,
                        parsed.plot_area_m2,
                        parsed.energy_hwb,
                        parsed.image_urls[0] if parsed.image_urls else None,
                        now_iso(),
                        source_url,
                        parsed.external_id,
                        parsed.external_id,
                    ),
                )
                con.commit()
            add_evidence(house_id, source_id, parsed.evidence)
            for url in parsed.image_urls:
                add_media(house_id, {"source_id": source_id, "kind": "image", "original_url": url, "download_status": "pending"})
            for url in parsed.pdf_urls:
                add_media(house_id, {"source_id": source_id, "kind": "pdf", "original_url": url, "download_status": "pending"})
        except Exception as exc:
            errors.append(f"{source.get('source_name') or source_url}: {str(exc)[:220]}")

    if not parsed_items:
        summary = "Aktualisierung fehlgeschlagen: " + " | ".join(errors)
        with connect() as con:
            con.execute("UPDATE houses SET last_refreshed_at = ?, last_refresh_summary = ?, updated_at = ? WHERE id = ?", (now_iso(), summary, now_iso(), house_id))
            con.commit()
        set_pipeline_stage(house_id, "error", "error", "Keine Inseratsquelle konnte aktualisiert werden.", error=summary)
        raise ValueError(summary)

    fields = ["title","location_text","address_status","price_eur","living_area_m2","plot_area_m2","rooms","year_built","heating","energy_hwb","energy_fgee","energy_class_hwb","energy_class_fgee"]
    updates = {field: _choose_value(parsed_items, field, house.get(field)) for field in fields}
    updates = {key:value for key,value in updates.items() if value not in (None,"")}
    update_house_details(house_id, updates)
    await main.download_pending_media_files(house_id)

    refreshed = get_house(house_id) or house
    after = {key: refreshed.get(key) for key in before}
    changed_fields = [key for key in before if str(before.get(key) or "") != str(after.get(key) or "")]
    media_after = len(list_media(house_id))
    new_media = max(0, media_after - media_before)
    summary_parts = [f"{len(parsed_items)} Quelle(n) aktualisiert", f"{new_media} neue Medien"]
    if changed_fields:
        summary_parts.append("geändert: " + ", ".join(changed_fields))
    if errors:
        summary_parts.append(f"{len(errors)} Quelle(n) mit Fehler")
    summary = " · ".join(summary_parts)
    timestamp = now_iso()
    with connect() as con:
        con.execute("UPDATE houses SET last_refreshed_at = ?, last_refresh_summary = ?, updated_at = ? WHERE id = ?", (timestamp, summary, timestamp, house_id))
        con.commit()

    set_pipeline_stage(house_id, "media_ready", "ok", summary)
    analysis_started = False
    if changed_fields or new_media:
        set_pipeline_stage(house_id, "exporting", "running", "Änderungen erkannt. Neue KI-Analyse wird bereitgestellt.")
        analysis_started = bool(await auto_export_house_to_github(house_id))
    return {"summary": summary, "changed_fields": changed_fields, "new_media": new_media, "analysis_started": analysis_started, "errors": errors}


def _patch_layout_references() -> None:
    main.layout = modern_layout
    for module in [product_ui, focused_ui, search_lifecycle_ui, search_automation_ui, dashboard_automation_ui]:
        if hasattr(module, "layout"):
            module.layout = modern_layout
    for module, attribute in [
        (product_ui, "PRODUCT_CSS"),
        (focused_ui, "FOCUS_CSS"),
        (search_lifecycle_ui, "LIFECYCLE_CSS"),
    ]:
        value = str(getattr(module, attribute, ""))
        if "--content: 1180px" not in value:
            setattr(module, attribute, value + MODERN_CSS)


def register_modern_ui(app: FastAPI) -> None:
    ensure_modern_schema()
    _patch_layout_references()
    _remove_route(app, "/", "GET")
    _remove_route(app, "/houses/{house_id}", "GET")
    _remove_route(app, "/settings/search", "GET")
    _remove_route(app, "/settings/search/new", "GET")

    @app.get("/", response_class=HTMLResponse)
    def modern_dashboard() -> HTMLResponse:
        houses = _active_houses()
        candidate_count = _candidate_count()
        body = f"""
        <div class="page-heading">
          <div><h1>Hausakten</h1><p>{len(houses)} aktive Objekte im Vergleich</p></div>
          <div class="page-actions"><a class="button secondary" href="search">{icon('search')} Suche</a><a class="button" href="import">{icon('plus')} Inserat</a></div>
        </div>
        <a class="card dashboard-banner" href="search" style="text-decoration:none;color:inherit">
          <div><strong>{candidate_count} nicht importierte Suchkandidaten</strong><div class="muted">Als übersichtliche Liste öffnen, prüfen, importieren oder ablehnen.</div></div>
          <span class="button secondary">Liste anzeigen</span>
        </a>
        <div class="house-grid">{''.join(_house_card(house) for house in houses) if houses else '<div class="card empty-state"><h2>Noch keine Hausakten</h2><p class="muted">Starte die Suche oder füge ein Inserat direkt hinzu.</p></div>'}</div>
        """
        return modern_layout("Hausakten", body, home_href="./")

    @app.get("/houses/{house_id}", response_class=HTMLResponse)
    def modern_house_detail(house_id: str) -> HTMLResponse:
        house = get_house(house_id)
        if not house:
            raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")
        hero = _hero_image(house)
        hero_html = f'<div class="hero"><img src="{hero}" alt="{esc(house.get("title"))}"><div class="hero-overlay"><h1>{esc(house.get("title"))}</h1><p>{esc(house.get("location_text") or "Lage unbekannt")}</p></div></div>' if hero else f'<div class="hero"><div class="hero-overlay"><h1>{esc(house.get("title"))}</h1><p>{esc(house.get("location_text") or "Lage unbekannt")}</p></div></div>'
        sources = list_sources(house_id)
        refresh_info = ""
        if house.get("last_refreshed_at"):
            refresh_info = f'<p class="muted">Zuletzt aktualisiert: {esc(format_datetime(house.get("last_refreshed_at")))} · {esc(house.get("last_refresh_summary") or "")}</p>'
        body = f"""
        {hero_html}
        <div class="detail-toolbar">
          <form method="post" action="{esc(house_id)}/refresh" data-loading="Inseratsdaten und Medien werden aktualisiert …"><button type="submit">{icon('refresh')} Aktualisieren</button></form>
          <a class="button secondary" href="{esc(house_id)}/merge">{icon('merge')} Zusammenlegen</a>
          <a class="button secondary" href="{esc(house_id)}/cover">{icon('image')} Titelbild</a>
          <a class="button secondary" href="{esc(house_id)}/edit">{icon('edit')} Bearbeiten</a>
        </div>
        {refresh_info}
        <div class="two-column">
          <div>
            <div class="card"><h2>Bewertung</h2>{house_score_html(house)}</div>
            <div class="section">{product_ui.analysis_card_html(house_id)}</div>
          </div>
          <div>
            <div class="card"><h2>Eckdaten</h2>{_facts_html(house)}</div>
            <div class="section">{product_ui.pipeline_card_html(house_id)}</div>
          </div>
        </div>
        <div class="section-title"><h2>Bilder</h2><a class="button ghost" href="{esc(house_id)}/cover">{icon('image')} Titelbild wählen</a></div>
        {_gallery_html(house_id)}
        <div class="section-title"><h2>Inseratsquellen</h2><span class="pill">{len(sources)} Quelle(n)</span></div>
        {_sources_html(house_id)}
        <div class="section grid">
          <div class="card"><h2>Exposé ergänzen</h2><p class="muted">PDF hochladen und erkannte Daten, Pläne und Bilder ergänzen.</p><form method="post" action="{esc(house_id)}/expose" enctype="multipart/form-data" data-loading="Exposé wird ausgewertet …"><input type="file" name="file" accept=".pdf,application/pdf" required><button type="submit">PDF hochladen</button></form></div>
          <div class="card"><h2>Notizen</h2><p>{esc(house.get('notes') or 'Noch keine Notizen.')}</p><a class="button secondary" href="{esc(house_id)}/edit">Bearbeiten</a></div>
        </div>
        <div class="section">{product_ui.diagnostics_html(house_id)}</div>
        <div class="section card danger-zone"><details><summary><strong>Weitere Aktionen</strong></summary><p class="muted">Objekt ablehnen oder endgültig löschen.</p><div class="action-row"><form method="post" action="{esc(house_id)}/reject" data-no-loading="true" onsubmit="return confirm('Objekt als abgelehnt markieren?');"><button class="secondary" type="submit">Ablehnen</button></form><form method="post" action="{esc(house_id)}/delete" data-loading="Hausakte wird gelöscht …" onsubmit="return confirm('Hausakte inklusive aller Daten endgültig löschen?');"><button class="danger" type="submit">Endgültig löschen</button></form></div></details></div>
        """
        return modern_layout(str(house.get("title") or "Hausakte"), body, home_href="../../")

    @app.post("/houses/{house_id}/refresh")
    async def refresh_house_route(house_id: str) -> RedirectResponse:
        try:
            await refresh_house_from_sources(house_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(f"../{house_id}", status_code=303)

    @app.get("/houses/{house_id}/merge", response_class=HTMLResponse)
    def merge_house_page(house_id: str) -> HTMLResponse:
        house = get_house(house_id)
        if not house:
            raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")
        candidates = [item for item in _active_houses() if str(item.get("id")) != house_id]
        options = []
        for candidate in candidates:
            candidate_id = str(candidate.get("id") or "")
            preview = preview_for_dashboard(candidate)
            options.append(f'<label class="merge-option"><input type="radio" name="source_house_id" value="{esc(candidate_id)}" required><span>{preview}</span><span><strong>{esc(candidate.get("title"))}</strong><br><span class="muted">{esc(candidate.get("location_text") or "Lage unbekannt")} · {len(list_sources(candidate_id))} Quelle(n)</span></span></label>')
        body = f"""
        <div class="page-heading"><div><h1>Hausakten zusammenlegen</h1><p>Die aktuelle Hausakte bleibt bestehen.</p></div><a class="button ghost" href="../{esc(house_id)}">{icon('back')} Zurück</a></div>
        <div class="card notice warning"><strong>Hauptakte:</strong> {esc(house.get('title'))}<br>Die gewählte zweite Hausakte wird vollständig eingegliedert und danach aus der Übersicht entfernt. Quellen und Bilder bleiben erhalten.</div>
        <form method="post" action="" data-loading="Hausakten werden zusammengeführt und neu analysiert …" onsubmit="return confirm('Ausgewählte Hausakte wirklich zusammenführen?');">
          <div class="merge-list section">{''.join(options) if options else '<div class="card empty-state"><h2>Keine zweite aktive Hausakte vorhanden</h2><p class="muted">Importiere zuerst das zweite Makler-Inserat als eigene Hausakte.</p></div>'}</div>
          {('<button type="submit">'+icon('merge')+' Jetzt zusammenlegen</button>') if options else ''}
        </form>
        """
        return modern_layout("Zusammenlegen", body, home_href="../../../")

    @app.get("/houses/{house_id}/cover", response_class=HTMLResponse)
    def cover_page(house_id: str) -> HTMLResponse:
        house = get_house(house_id)
        if not house:
            raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")
        selected = str(house.get("preview_media_id") or "")
        choices = []
        for item in _house_images(house_id):
            media_id = str(item.get("id") or "")
            is_selected = media_id == selected
            choices.append(f'<div class="cover-choice {"selected" if is_selected else ""}"><img src="../../media/{esc(media_id)}" alt="Galeriebild"><form method="post" action="../preview/{esc(media_id)}" data-no-loading="true"><button type="submit" title="Als Titelbild verwenden" aria-label="Als Titelbild verwenden">{icon("check") if is_selected else icon("image")}</button></form></div>')
        reset = f'<form method="post" action="../preview/clear" data-no-loading="true"><button class="secondary" type="submit">Automatische Auswahl</button></form>' if selected else ''
        body = f"""
        <div class="page-heading"><div><h1>Titelbild wählen</h1><p>Die Galerie bleibt unverändert; hier wird nur das Bild für Übersicht und Kopfbereich gewählt.</p></div><a class="button ghost" href="../{esc(house_id)}">{icon('back')} Zurück</a></div>
        <div class="action-row">{reset}</div>
        <div class="cover-grid section">{''.join(choices) if choices else '<div class="card empty-state"><p class="muted">Noch keine geladenen Bilder vorhanden.</p></div>'}</div>
        """
        return modern_layout("Titelbild", body, home_href="../../../")

    @app.get("/houses/{house_id}/edit", response_class=HTMLResponse)
    def edit_house_page(house_id: str) -> HTMLResponse:
        house = get_house(house_id)
        if not house:
            raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")
        body = f"""
        <div class="page-heading"><div><h1>Hausakte bearbeiten</h1><p>Manuell korrigierte Werte bleiben bis zur nächsten Aktualisierung erhalten.</p></div><a class="button ghost" href="../{esc(house_id)}">{icon('back')} Zurück</a></div>
        <div class="card">
          <form method="post" action="" data-loading="Hausakte wird gespeichert …">
            <label>Titel</label><input name="title" value="{esc(house.get('title'))}">
            <label>Adresse / Lage</label><input name="location_text" value="{esc(house.get('location_text'))}">
            <label>Adressstatus</label><select name="address_status"><option value="unknown" {'selected' if house.get('address_status') == 'unknown' else ''}>unbekannt</option><option value="municipality_only" {'selected' if house.get('address_status') == 'municipality_only' else ''}>nur Ort/Gemeinde</option><option value="hint" {'selected' if house.get('address_status') == 'hint' else ''}>Adresshinweis</option><option value="exact" {'selected' if house.get('address_status') == 'exact' else ''}>genaue Adresse</option></select>
            <div class="grid"><div><label>Preis €</label><input name="price_eur" type="number" value="{esc(house.get('price_eur'))}"></div><div><label>Wohnfläche m²</label><input name="living_area_m2" type="number" step="0.1" value="{esc(house.get('living_area_m2'))}"></div><div><label>Grundstück m²</label><input name="plot_area_m2" type="number" step="0.1" value="{esc(house.get('plot_area_m2'))}"></div><div><label>Zimmer</label><input name="rooms" type="number" step="0.1" value="{esc(house.get('rooms'))}"></div><div><label>Baujahr</label><input name="year_built" type="number" value="{esc(house.get('year_built'))}"></div><div><label>HWB</label><input name="energy_hwb" type="number" step="0.1" value="{esc(house.get('energy_hwb'))}"></div><div><label>fGEE</label><input name="energy_fgee" type="number" step="0.01" value="{esc(house.get('energy_fgee'))}"></div><div><label>Heizung</label><input name="heating" value="{esc(house.get('heating'))}"></div></div>
            <input type="hidden" name="preview_image_url" value="{esc(house.get('preview_image_url'))}">
            <label>Notizen</label><textarea name="notes" rows="5">{esc(house.get('notes'))}</textarea>
            <button type="submit">Speichern</button>
          </form>
        </div>
        """
        return modern_layout("Bearbeiten", body, home_href="../../../")

    @app.get("/settings/search", response_class=HTMLResponse)
    def modern_search_settings() -> HTMLResponse:
        profiles = list_search_profiles()
        cards = []
        for profile in profiles:
            pid = str(profile.get("id") or "")
            with connect() as con:
                count = int(con.execute("SELECT COUNT(*) FROM search_candidates WHERE profile_id = ?", (pid,)).fetchone()[0] or 0)
            cards.append(f'<div class="card"><div class="page-heading" style="margin:0"><div><h2 style="font-size:20px">{esc(profile.get("name"))}</h2><p>{esc(profile.get("regions") or "Keine Region")}</p></div><span class="pill {"good" if int(profile.get("enabled") or 0) else "bad"}">{"aktiv" if int(profile.get("enabled") or 0) else "pausiert"}</span></div><p><span class="pill">{esc(profile.get("automation_mode") or "manual")}</span><span class="pill">alle {esc(profile.get("run_interval_minutes") or 60)} Min.</span><span class="pill">{count} Kandidaten</span></p><div class="action-row"><a class="button secondary" href="search/{esc(pid)}/edit">{icon("edit")} Bearbeiten</a><form method="post" action="search/profiles/{esc(pid)}/delete" data-no-loading="true" onsubmit="return confirm(\'Suchprofil inklusive Kandidaten und Preisverlauf löschen?\');"><button class="danger" type="submit">{icon("trash")} Löschen</button></form></div></div>')
        body = f"""
        <div class="page-heading"><div><h1>Suchprofile</h1><p>Regionen, Filter und Automatik vollständig bearbeiten.</p></div><a class="button" href="search/new">{icon('plus')} Neues Profil</a></div>
        <div class="grid">{''.join(cards) if cards else '<div class="card empty-state"><h2>Noch kein Suchprofil</h2></div>'}</div>
        """
        return modern_layout("Suchprofile", body, home_href="../../")

    @app.get("/settings/search/new", response_class=HTMLResponse)
    def modern_new_profile() -> HTMLResponse:
        body = f'<div class="page-heading"><div><h1>Neues Suchprofil</h1><p>Willhaben-Suche konfigurieren.</p></div><a class="button ghost" href="../search">{icon("back")} Zurück</a></div><div class="card">{_profile_form(None,"profiles")}</div>'
        return modern_layout("Neues Suchprofil", body, home_href="../../../")

    @app.get("/settings/search/{profile_id}/edit", response_class=HTMLResponse)
    def edit_profile_page(profile_id: str) -> HTMLResponse:
        profile = get_search_profile(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Suchprofil nicht gefunden")
        body = f'<div class="page-heading"><div><h1>Suchprofil bearbeiten</h1><p>Alle Filter und Automatikwerte können geändert werden.</p></div><a class="button ghost" href="../../search">{icon("back")} Zurück</a></div><div class="card">{_profile_form(profile,"")}</div>'
        return modern_layout("Suchprofil bearbeiten", body, home_href="../../../../")

    @app.post("/settings/search/{profile_id}/edit")
    async def edit_profile_route(
        profile_id: str,
        name: str = Form(...),
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
        if not get_search_profile(profile_id):
            raise HTTPException(status_code=404, detail="Suchprofil nicht gefunden")
        try:
            data = _profile_update_data(name, regions, area_ids, search_url, max_price_eur, soft_max_price_eur, min_living_area_m2, min_plot_area_m2, exclude_roads, hwb_warn, hwb_reject, oil_policy)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        data["updated_at"] = now_iso()
        with connect() as con:
            sql = ", ".join(f"{key} = ?" for key in data)
            con.execute(f"UPDATE search_profiles SET {sql} WHERE id = ?", list(data.values()) + [profile_id])
            con.commit()
        mode = automation_mode if automation_mode in {"manual","review","automatic"} else "review"
        update_profile_automation(profile_id, {"enabled":1 if enabled else 0,"area_ids":str(area_ids or "").strip(),"automation_mode":mode,"run_interval_minutes":max(15,min(int(run_interval_minutes),1440)),"auto_import_enabled":1 if mode == "automatic" else 0,"max_results":max(10,min(int(max_results),160)),"auto_import_min_score":max(0,min(int(auto_import_min_score),100)),"auto_import_limit_per_run":max(1,min(int(auto_import_limit_per_run),10)),"last_run_status":"Einstellungen aktualisiert","last_error":None})
        return RedirectResponse("../../search", status_code=303)
