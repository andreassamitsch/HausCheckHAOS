#!/usr/bin/env sh
set -eu

DATA_DIR="${HAUSCHECK_DATA_DIR:-/share/hauscheck}"
mkdir -p "${DATA_DIR}"
mkdir -p "${DATA_DIR}/projects"
mkdir -p "${DATA_DIR}/logs"

export HAUSCHECK_DATA_DIR="${DATA_DIR}"
export PYTHONUNBUFFERED=1

# v0.5.1 runtime migration:
# - Bewertungs-MVP in die UI einblenden
# - Vorschaubilder bevorzugt aus der Portal-/Willhaben-Übersicht übernehmen
python3 - <<'PY'
from pathlib import Path

path = Path('/app/app/main.py')
if path.exists():
    text = path.read_text(encoding='utf-8')
    text = text.replace('app = FastAPI(title=APP_NAME, version="0.4.6")', 'app = FastAPI(title=APP_NAME, version="0.5.1")')
    text = text.replace('app = FastAPI(title=APP_NAME, version="0.5.0")', 'app = FastAPI(title=APP_NAME, version="0.5.1")')
    text = text.replace('v0.4.6: mobile Kartenansicht und Ladehinweise.', 'v0.5.1: Bewertung und Portal-Vorschaubilder.')
    text = text.replace('v0.5.0: regelbasierte Erstbewertung / Score vorgezogen.', 'v0.5.1: Bewertung und Portal-Vorschaubilder.')

    text = text.replace(
        'from app.parser import ParsedListing, extract_listing_links, parse_listing, title_from_listing_url',
        'from app.parser import ParsedListing, extract_listing_candidates, extract_listing_links, parse_listing, title_from_listing_url'
    )

    if '.score-box {' not in text:
        text = text.replace(
            '    .source-links {{ font-size: 13px; line-height: 1.45; overflow-wrap: anywhere; }}\n',
            '    .source-links {{ font-size: 13px; line-height: 1.45; overflow-wrap: anywhere; }}\n'
            '    .score-box {{ margin: 8px 0; padding: 9px; border-radius: 12px; background: #0f151b; border: 1px solid #26323e; }}\n'
            '    .score-head {{ display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 6px; }}\n'
            '    .score-value {{ font-size: 20px; font-weight: 900; }}\n'
            '    .score-label {{ font-weight: 800; }}\n'
            '    .score-bar {{ height: 8px; border-radius: 999px; background: #26323e; overflow: hidden; margin: 6px 0; }}\n'
            '    .score-fill {{ height: 100%; background: #8fd3ff; border-radius: 999px; }}\n'
            '    .score-reasons {{ color: #aab4bd; font-size: 12px; line-height: 1.35; }}\n'
        )

    if 'def score_property(' not in text:
        needle = '''def facts_from_parsed(parsed: ParsedListing) -> dict[str, object]:
    return {
        "price_eur": parsed.price_eur,
        "living_area_m2": parsed.living_area_m2,
        "plot_area_m2": parsed.plot_area_m2,
        "energy_hwb": parsed.energy_hwb,
        "preview_image_url": parsed.image_urls[0] if parsed.image_urls else None,
    }

'''
        scoring = r'''def value_float(data: dict[str, object], key: str) -> float | None:
    value = data.get(key)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def score_property(data: dict[str, object], status: str = "new") -> dict[str, object]:
    score = 55
    reasons: list[str] = []
    known = 0

    price = value_float(data, "price_eur")
    living = value_float(data, "living_area_m2")
    plot = value_float(data, "plot_area_m2")
    hwb = value_float(data, "energy_hwb")

    if status == "filtered":
        score -= 25
        reasons.append("harte Filterregel verletzt")
    elif status == "review":
        score -= 8
        reasons.append("manuelle Prüfung nötig")
    elif status == "imported":
        score += 2

    if price is None:
        reasons.append("Preis fehlt")
    else:
        known += 1
        if price <= 320000:
            score += 14
            reasons.append("Preis sehr attraktiv")
        elif price <= 380000:
            score += 8
            reasons.append("Preis im Zielbereich")
        elif price <= 400000:
            score += 1
            reasons.append("Preis an der Obergrenze")
        else:
            score -= 18
            reasons.append("Preis über Zielbereich")

    if living is None:
        reasons.append("Wohnfläche fehlt")
    else:
        known += 1
        if living >= 160:
            score += 12
            reasons.append("große Wohnfläche")
        elif living >= 130:
            score += 8
            reasons.append("Wohnfläche gut")
        elif living >= 120:
            score += 2
            reasons.append("Wohnfläche ausreichend")
        else:
            score -= 18
            reasons.append("Wohnfläche eher knapp")

    if plot is None:
        reasons.append("Grundstück fehlt")
    else:
        known += 1
        if plot >= 1200:
            score += 12
            reasons.append("sehr großes Grundstück")
        elif plot >= 900:
            score += 9
            reasons.append("großes Grundstück")
        elif plot >= 700:
            score += 5
            reasons.append("Grundstück im Wunschbereich")
        elif plot >= 500:
            score -= 1
            reasons.append("Grundstück eher klein")
        else:
            score -= 10
            reasons.append("Grundstück deutlich klein")

    if hwb is None:
        reasons.append("HWB fehlt")
    else:
        known += 1
        if hwb <= 80:
            score += 12
            reasons.append("sehr guter HWB")
        elif hwb <= 150:
            score += 6
            reasons.append("brauchbarer HWB")
        elif hwb <= 250:
            score -= 5
            reasons.append("HWB prüfen")
        elif hwb <= 300:
            score -= 12
            reasons.append("HWB kritisch")
        else:
            score -= 22
            reasons.append("HWB sehr kritisch")

    score = max(0, min(100, int(round(score))))
    if score >= 82:
        label = "sehr interessant"
        pill = "good"
    elif score >= 68:
        label = "interessant"
        pill = "good"
    elif score >= 50:
        label = "prüfen"
        pill = "warn"
    else:
        label = "kritisch"
        pill = "bad"

    confidence = "hoch" if known >= 4 else "mittel" if known >= 2 else "niedrig"
    return {"score": score, "label": label, "pill": pill, "confidence": confidence, "reasons": reasons[:4]}


def score_html_from_data(data: dict[str, object], status: str = "new") -> str:
    result = score_property(data, status)
    score = int(result["score"])
    reasons = " · ".join(esc(reason) for reason in result["reasons"])
    return f"""
    <div class="score-box">
      <div class="score-head">
        <span class="score-value">{score}/100</span>
        <span class="pill {esc(result['pill'])}">{esc(result['label'])}</span>
      </div>
      <div class="score-bar"><div class="score-fill" style="width:{score}%"></div></div>
      <div class="score-reasons">Bewertungssicherheit: {esc(result['confidence'])}<br>{reasons}</div>
    </div>
    """


def candidate_score_html(candidate: dict[str, object], status: str = "new") -> str:
    return score_html_from_data(candidate, status)


def house_score_html(house: dict[str, object]) -> str:
    return score_html_from_data(house, str(house.get("status") or "new"))


'''
        text = text.replace(needle, needle + scoring)

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

exec uvicorn app.main:app --host 0.0.0.0 --port 8088
