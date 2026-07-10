#!/usr/bin/env sh
set -eu

DATA_DIR="${HAUSCHECK_DATA_DIR:-/share/hauscheck}"
mkdir -p "${DATA_DIR}"
mkdir -p "${DATA_DIR}/projects"
mkdir -p "${DATA_DIR}/logs"

export HAUSCHECK_DATA_DIR="${DATA_DIR}"
export PYTHONUNBUFFERED=1

if [ -f /data/options.json ]; then
  export HAUSCHECK_API_TOKEN="$(python3 - <<'PY'
import json
from pathlib import Path
try:
    data = json.loads(Path('/data/options.json').read_text(encoding='utf-8'))
    print(str(data.get('api_token') or '').strip())
except Exception:
    print('')
PY
)"
fi

python3 - <<'PY'
from pathlib import Path

path = Path('/app/app/main.py')
if path.exists():
    text = path.read_text(encoding='utf-8')

    for old in ['0.4.6', '0.5.0', '0.5.1', '0.5.2', '0.5.3', '0.5.4']:
        text = text.replace(f'app = FastAPI(title=APP_NAME, version="{old}")', 'app = FastAPI(title=APP_NAME, version="0.5.5")')
    for old_text in [
        'v0.4.6: mobile Kartenansicht und Ladehinweise.',
        'v0.5.0: regelbasierte Erstbewertung / Score vorgezogen.',
        'v0.5.1: Bewertung und Portal-Vorschaubilder.',
        'v0.5.2: Bewertung, Portal-Vorschaubilder und ChatGPT-Bridge.',
        'v0.5.4: manuelles ChatGPT-Analysepaket.',
    ]:
        text = text.replace(old_text, 'v0.5.5: Hausakten bearbeiten, löschen, Galerie und Exposé-PDF.')

    text = text.replace(
        'from app.parser import ParsedListing, extract_listing_links, parse_listing, title_from_listing_url',
        'from app.parser import ParsedListing, extract_listing_candidates, extract_listing_links, parse_listing, title_from_listing_url'
    )
    if 'from app.ui_helpers import candidate_score_html, house_score_html' not in text:
        text = text.replace(
            'from app.parser import ParsedListing, extract_listing_candidates, extract_listing_links, parse_listing, title_from_listing_url\n',
            'from app.parser import ParsedListing, extract_listing_candidates, extract_listing_links, parse_listing, title_from_listing_url\n'
            'from app.ui_helpers import candidate_score_html, house_score_html\n'
            'from app.analysis_package import analysis_status_html\n'
            'from app.house_manage import dashboard_preview_html, gallery_slider_html, edit_house_form_html, delete_house_form_html, expose_upload_html, set_house_preview\n'
        )
    elif 'from app.house_manage import dashboard_preview_html' not in text:
        text = text.replace(
            'from app.ui_helpers import candidate_score_html, house_score_html\n',
            'from app.ui_helpers import candidate_score_html, house_score_html\n'
            'from app.house_manage import dashboard_preview_html, gallery_slider_html, edit_house_form_html, delete_house_form_html, expose_upload_html, set_house_preview\n'
        )
        if 'from app.analysis_package import analysis_status_html' not in text:
            text = text.replace(
                'from app.house_manage import dashboard_preview_html, gallery_slider_html, edit_house_form_html, delete_house_form_html, expose_upload_html, set_house_preview\n',
                'from app.house_manage import dashboard_preview_html, gallery_slider_html, edit_house_form_html, delete_house_form_html, expose_upload_html, set_house_preview\nfrom app.analysis_package import analysis_status_html\n'
            )

    if '.score-box {' not in text:
        text = text.replace(
            '    .source-links {{ font-size: 13px; line-height: 1.45; overflow-wrap: anywhere; }}\n',
            '    .source-links {{ font-size: 13px; line-height: 1.45; overflow-wrap: anywhere; }}\n'
            '    .score-box {{ margin: 8px 0; padding: 9px; border-radius: 12px; background: #0f151b; border: 1px solid #26323e; }}\n'
            '    .score-head {{ display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 6px; }}\n'
            '    .score-value {{ font-size: 20px; font-weight: 900; }}\n'
            '    .score-bar {{ height: 8px; border-radius: 999px; background: #26323e; overflow: hidden; margin: 6px 0; }}\n'
            '    .score-fill {{ height: 100%; background: #8fd3ff; border-radius: 999px; }}\n'
            '    .score-reasons {{ color: #aab4bd; font-size: 12px; line-height: 1.35; }}\n'
        )

    if '.gallery-slider {' not in text:
        text = text.replace(
            '    .source-links {{ font-size: 13px; line-height: 1.45; overflow-wrap: anywhere; }}\n',
            '    .source-links {{ font-size: 13px; line-height: 1.45; overflow-wrap: anywhere; }}\n'
            '    .gallery-slider {{ display: flex; gap: 10px; overflow-x: auto; scroll-snap-type: x mandatory; padding-bottom: 8px; }}\n'
            '    .gallery-slide {{ flex: 0 0 min(86vw, 760px); scroll-snap-align: start; border-radius: 16px; overflow: hidden; background: #0b0f14; border: 1px solid #26323e; }}\n'
            '    .gallery-slide img {{ width: 100%; max-height: 520px; object-fit: contain; display: block; }}\n'
            '    .compact-card details {{ margin-top: 4px; }}\n'
            '    button.danger, .button.danger {{ background: #9f2d2d; color: white; }}\n'
            '    .danger-zone {{ border-color: #663333; }}\n'
        )

    text = text.replace(
        '        img = first_local_image(house["id"])\n        image_html = f\'<img class="thumb" src="{img}" alt="Bild">\' if img else \'<div class="muted">Noch kein lokales Bild</div>\'',
        '        image_html = dashboard_preview_html(house)'
    )

    # alte / überflüssige Buttons aus der Hausakte entfernen; Routen bleiben als Fallback vorhanden.
    text = text.replace('      <a class="button secondary" href="{house_id}/briefing">Analysebriefing</a>\n', '')
    text = text.replace('      <form method="post" action="{house_id}/download-media" data-loading="Medien werden heruntergeladen …" style="display:inline"><button type="submit">Medien erneut herunterladen</button></form>\n', '')
    text = text.replace('      <form method="post" action="{house_id}/cleanup-media" data-loading="Medien werden bereinigt …" style="display:inline"><button class="secondary" type="submit">Medien bereinigen</button></form>\n', '')

    if '{candidate_score_html(cand, status)}' not in text:
        text = text.replace(
            '                <div>{status_pill(status)}</div>\n                <div class="listing-facts">',
            '                <div>{status_pill(status)}</div>\n                {candidate_score_html(cand, status)}\n                <div class="listing-facts">'
        )

    if '{house_score_html(house)}' not in text:
        text = text.replace(
            '      <p class="muted">{esc(house.get(\'location_text\') or \'Lage unbekannt\')}</p>\n      <p>',
            '      <p class="muted">{esc(house.get(\'location_text\') or \'Lage unbekannt\')}</p>\n      {house_score_html(house)}\n      <p>'
        )

    text = text.replace(
        '    media_items = []\n    for item in media:\n        if item.get("kind") == "image" and item.get("download_status") == "downloaded":\n            media_items.append(f"<a href=\'../media/{item[\'id\']}\' target=\'_blank\'><img class=\'thumb\' src=\'../media/{item[\'id\']}\' alt=\'Bild\'></a>")\n    media_html = "".join(media_items) if media_items else "<p class=\'muted\'>Noch keine heruntergeladenen Bilder.</p>"',
        '    media_html = gallery_slider_html(house_id)'
    )

    if '{analysis_status_html(house_id)}' not in text:
        text = text.replace(
            '    </div>\n    <div class="card"><h2>Bilder</h2>',
            '    </div>\n    {analysis_status_html(house_id)}\n    {edit_house_form_html(house)}\n    {expose_upload_html(house_id)}\n    <div class="card"><h2>Bilder</h2>'
        )
    else:
        if '{edit_house_form_html(house)}' not in text:
            text = text.replace('{analysis_status_html(house_id)}\n    <div class="card"><h2>Bilder</h2>', '{analysis_status_html(house_id)}\n    {edit_house_form_html(house)}\n    {expose_upload_html(house_id)}\n    <div class="card"><h2>Bilder</h2>')

    if '{delete_house_form_html(house_id)}' not in text:
        text = text.replace(
            '    <div class="card"><h2>Feldherkunft</h2><table><tr><th>Feld</th><th>Wert</th><th>Sicherheit</th><th>Snippet</th></tr>{evidence_rows}</table></div>',
            '    <div class="card"><h2>Feldherkunft</h2><table><tr><th>Feld</th><th>Wert</th><th>Sicherheit</th><th>Snippet</th></tr>{evidence_rows}</table></div>\n    {delete_house_form_html(house_id)}'
        )

    if 'name="preview_image_url"' not in text:
        text = text.replace(
            '              <input type="hidden" name="url" value="{esc(cand.get(\'source_url\'))}">\n              <button type="submit">Importieren inkl. Bilder</button>',
            '              <input type="hidden" name="url" value="{esc(cand.get(\'source_url\'))}">\n              <input type="hidden" name="preview_image_url" value="{esc(cand.get(\'preview_image_url\'))}">\n              <button type="submit">Importieren</button>'
        )

    text = text.replace(
        'async def import_url(url: str = Form(...)) -> RedirectResponse:',
        'async def import_url(url: str = Form(...), preview_image_url: str | None = Form(None)) -> RedirectResponse:'
    )
    if 'set_house_preview(house["id"], preview_image_url)' not in text:
        text = text.replace(
            '    hdir = project_dir(house["id"])\n',
            '    set_house_preview(house["id"], preview_image_url)\n    hdir = project_dir(house["id"])\n'
        )

    start = text.find('async def run_search_profile(profile_id: str, max_results: int = 80) -> int:')
    end = text.find('\n\n@app.post("/search/profiles")', start)
    if start != -1 and end != -1:
        new_run = '''async def run_search_profile(profile_id: str, max_results: int = 80) -> int:
    profile = get_search_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Suchprofil nicht gefunden")

    overview_candidates = []
    seen_keys: set[str] = set()
    for search_url in resolve_search_urls(profile):
        raw_html = await fetch_html(search_url)
        for candidate in extract_listing_candidates(raw_html, search_url):
            key = listing_key(candidate.url)
            if key not in seen_keys:
                seen_keys.add(key)
                overview_candidates.append(candidate)

    overview_candidates = overview_candidates[: max(1, min(max_results, 160))]
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        for candidate in overview_candidates:
            link = candidate.url
            overview_preview = candidate.preview_image_url
            if source_url_exists(link):
                facts = {"preview_image_url": overview_preview} if overview_preview else None
                upsert_search_candidate(profile_id, link, candidate.title or title_from_listing_url(link), status="imported", facts=facts)
                continue
            try:
                detail = await client.get(link)
                detail.raise_for_status()
                parsed = parse_listing(link, detail.text)
                status, reasons = evaluate_candidate(profile, parsed)
                facts = facts_from_parsed(parsed)
                if overview_preview:
                    facts["preview_image_url"] = overview_preview
                upsert_search_candidate(profile_id, link, parsed.title or candidate.title or title_from_listing_url(link), status=status, facts=facts, filter_reasons=reasons)
            except Exception as exc:
                facts = {"preview_image_url": overview_preview} if overview_preview else None
                upsert_search_candidate(profile_id, link, candidate.title or title_from_listing_url(link), status="review", facts=facts, filter_reasons=[f"Detailprüfung fehlgeschlagen: {str(exc)[:180]}"])
    update_search_profile_run(profile_id, len(overview_candidates))
    return len(overview_candidates)'''
        text = text[:start] + new_run + text[end:]

    path.write_text(text, encoding='utf-8')

ap = Path('/app/app/analysis_package.py')
if ap.exists():
    txt = ap.read_text(encoding='utf-8')
    if 'address_hints' not in txt:
        txt = txt.replace(
            '            "image_findings": {\n',
            '            "address_hints": {"type": "array", "items": {"type": "object", "properties": {"hint": {"type": "string"}, "basis": {"type": "string"}, "confidence": {"enum": ["niedrig", "mittel", "hoch"]}}}},\n            "image_findings": {\n'
        )
        txt = txt.replace(
            '  "image_findings": [],\n  "recommendation": "...",',
            '  "address_hints": [],\n  "image_findings": [],\n  "recommendation": "...",'
        )
        txt = txt.replace(
            '- Besichtigungsfragen und nächste Prüfpunkte\n',
            '- Besichtigungsfragen und nächste Prüfpunkte\n- versuche keine exakte Adresse zu erraten, aber gib mögliche Orts-/Lagehinweise als `address_hints` an, wenn Bilder, Text oder Quellen dafür eine Basis liefern; immer mit `basis` und `confidence`\n'
        )
    if 'Adress-/Lagehinweise' not in txt:
        txt = txt.replace(
            '        risk_html = "".join(f"<li>{esc(item)}</li>" for item in risks[:6]) or "<li class=\'muted\'>Keine Risiken importiert.</li>"\n        analysis_html = f"""',
            '        risk_html = "".join(f"<li>{esc(item)}</li>" for item in risks[:6]) or "<li class=\'muted\'>Keine Risiken importiert.</li>"\n        address_hints = analysis.get("address_hints") or []\n        address_html = "".join(f"<li>{esc(item.get(\'hint\'))} <span class=\'muted\'>({esc(item.get(\'confidence\'))}; {esc(item.get(\'basis\'))})</span></li>" for item in address_hints[:5] if isinstance(item, dict)) or "<li class=\'muted\'>Keine Adresshinweise importiert.</li>"\n        analysis_html = f"""'
        )
        txt = txt.replace(
            '        <p><strong>Empfehlung:</strong> {esc(recommendation)}</p>\n        <div class="grid"><div><strong>Chancen</strong><ul>{positive_html}</ul></div><div><strong>Risiken</strong><ul>{risk_html}</ul></div></div>',
            '        <p><strong>Empfehlung:</strong> {esc(recommendation)}</p>\n        <p><strong>Adress-/Lagehinweise:</strong></p><ul>{address_html}</ul>\n        <div class="grid"><div><strong>Chancen</strong><ul>{positive_html}</ul></div><div><strong>Risiken</strong><ul>{risk_html}</ul></div></div>'
        )
    ap.write_text(txt, encoding='utf-8')
PY

exec uvicorn app.bootstrap:app --host 0.0.0.0 --port 8088
