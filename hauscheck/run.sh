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

# Runtime-UI-Migration für Installationen, bei denen app/main.py noch auf 0.4.x basiert.
# Die Zusatzrouten liegen sauber in app.bootstrap / app.analysis_package.
python3 - <<'PY'
from pathlib import Path

path = Path('/app/app/main.py')
if path.exists():
    text = path.read_text(encoding='utf-8')

    for old in ['0.4.6', '0.5.0', '0.5.1', '0.5.2', '0.5.3']:
        text = text.replace(f'app = FastAPI(title=APP_NAME, version="{old}")', 'app = FastAPI(title=APP_NAME, version="0.5.4")')
    for old_text in [
        'v0.4.6: mobile Kartenansicht und Ladehinweise.',
        'v0.5.0: regelbasierte Erstbewertung / Score vorgezogen.',
        'v0.5.1: Bewertung und Portal-Vorschaubilder.',
        'v0.5.2: Bewertung, Portal-Vorschaubilder und ChatGPT-Bridge.',
    ]:
        text = text.replace(old_text, 'v0.5.4: manuelles ChatGPT-Analysepaket.')

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

    if '{analysis_status_html(house_id)}' not in text:
        text = text.replace(
            '      <a class="button secondary" href="{house_id}/briefing">Analysebriefing</a>\n    </div>\n    <div class="card"><h2>Bilder</h2>',
            '      <a class="button secondary" href="{house_id}/briefing">Analysebriefing</a>\n    </div>\n    {analysis_status_html(house_id)}\n    <div class="card"><h2>Bilder</h2>'
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
PY

exec uvicorn app.bootstrap:app --host 0.0.0.0 --port 8088
