#!/usr/bin/env sh
set -eu

DATA_DIR="${HAUSCHECK_DATA_DIR:-/share/hauscheck}"
mkdir -p "${DATA_DIR}"
mkdir -p "${DATA_DIR}/projects"
mkdir -p "${DATA_DIR}/logs"

export HAUSCHECK_DATA_DIR="${DATA_DIR}"
export PYTHONUNBUFFERED=1

# v0.4.4 hotfix/runtime migration:
# - Willhaben supports postal-code searches via areaId, e.g. Wies = 8551.
# - New profiles can use multiple PLZ/areaIds; the generated URLs are stored as
#   newline-separated portal sources in search_url.
# - Existing auto-generated areaId=60351 profiles are migrated to areaId=8551.
# - Manual radius URLs with sfId/lat/lon are left untouched.
python3 - <<'PY'
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

DATA_DIR = Path(os.environ.get("HAUSCHECK_DATA_DIR", "/share/hauscheck"))
DB_PATH = DATA_DIR / "hauscheck.db"
MAIN_PATH = Path("/app/app/main.py")
WILLHABEN_BASE = "https://www.willhaben.at/iad/immobilien/haus-kaufen/haus-angebote"
DEFAULT_AREA_ID = "8551"


def numeric(value, default):
    if value is None or str(value).strip() == "":
        return default
    try:
        text = str(value).strip().replace(" ", "")
        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        return int(float(text))
    except Exception:
        return default


def build_url(row, area_id=DEFAULT_AREA_ID):
    price = numeric(row["max_price_eur"] if row["max_price_eur"] is not None else row["soft_max_price_eur"], 400000)
    living = numeric(row["min_living_area_m2"], 120)
    query = urlencode({
        "areaId": str(area_id).strip() or DEFAULT_AREA_ID,
        "page": 1,
        "PRICE_TO": price,
        "ESTATE_SIZE/LIVING_AREA_FROM": living,
    })
    return f"{WILLHABEN_BASE}?{query}"


def patch_main():
    if not MAIN_PATH.exists():
        return
    text = MAIN_PATH.read_text(encoding="utf-8")

    text = text.replace('WILLHABEN_DEFAULT_AREA_ID = "60351"', 'WILLHABEN_DEFAULT_AREA_ID = "8551"')
    text = text.replace('app = FastAPI(title=APP_NAME, version="0.4.2")', 'app = FastAPI(title=APP_NAME, version="0.4.4")')
    text = text.replace('app = FastAPI(title=APP_NAME, version="0.4.3")', 'app = FastAPI(title=APP_NAME, version="0.4.4")')
    text = text.replace('v0.4.2: Zahlenparser-Fix für Wohnfläche/Preis aus SQLite.', 'v0.4.4: mehrere Willhaben-PLZ/areaIds pro Suchprofil.')
    text = text.replace('v0.4.3: Willhaben nutzt PLZ areaId=8551 als Standardquelle.', 'v0.4.4: mehrere Willhaben-PLZ/areaIds pro Suchprofil.')
    text = text.replace('leer lassen = automatische Willhaben-Suche areaId=60351', 'leer lassen = automatische Willhaben-Suche über PLZ/areaIds')
    text = text.replace('leer lassen = automatische Willhaben-Suche PLZ/areaId=8551', 'leer lassen = automatische Willhaben-Suche über PLZ/areaIds')
    text = text.replace('Automatische Willhaben-Quelle: areaId=60351, sort=1, rows=30, page=1, PRICE_TO und ESTATE_SIZE/LIVING_AREA_FROM aus den Kriterien.', 'Automatische Willhaben-Quelle: pro PLZ/areaId eine URL mit page=1, PRICE_TO und ESTATE_SIZE/LIVING_AREA_FROM aus den Kriterien.')
    text = text.replace('Automatische Willhaben-Quelle: areaId=8551, page=1, PRICE_TO und ESTATE_SIZE/LIVING_AREA_FROM aus den Kriterien.', 'Automatische Willhaben-Quelle: pro PLZ/areaId eine URL mit page=1, PRICE_TO und ESTATE_SIZE/LIVING_AREA_FROM aus den Kriterien.')

    # Replace Willhaben URL builder block with multi-areaId support.
    start = text.find('def build_willhaben_auto_url(profile: dict[str, object]) -> str:')
    end = text.find('\ndef evaluate_candidate', start)
    if start != -1 and end != -1:
        new_block = '''def parse_area_ids(value: object) -> list[str]:\n    raw = str(value or "").strip()\n    if not raw:\n        raw = WILLHABEN_DEFAULT_AREA_ID\n    items = [item.strip() for item in re.split(r"[,;\\s]+", raw) if item.strip()]\n    result: list[str] = []\n    for item in items:\n        if item not in result:\n            result.append(item)\n    return result or [WILLHABEN_DEFAULT_AREA_ID]\n\n\ndef build_willhaben_url_for_area(profile: dict[str, object], area_id: str) -> str:\n    max_price = optional_int(str(profile.get("max_price_eur") or "")) or optional_int(str(profile.get("soft_max_price_eur") or "")) or 400000\n    min_living = optional_float(str(profile.get("min_living_area_m2") or "")) or 120\n    params = [\n        ("areaId", str(area_id).strip() or WILLHABEN_DEFAULT_AREA_ID),\n        ("page", "1"),\n        ("PRICE_TO", str(int(max_price))),\n        ("ESTATE_SIZE/LIVING_AREA_FROM", str(int(min_living))),\n    ]\n    query = "&".join(f"{key}={value}" for key, value in params)\n    return f"{WILLHABEN_AUTO_BASE}?{query}"\n\n\ndef build_willhaben_auto_urls(profile: dict[str, object], area_ids: object | None = None) -> list[str]:\n    return [build_willhaben_url_for_area(profile, area_id) for area_id in parse_area_ids(area_ids)]\n\n\ndef resolve_search_urls(profile: dict[str, object]) -> list[str]:\n    search_url = str(profile.get("search_url") or "").strip()\n    if search_url:\n        urls = [url.strip() for url in re.split(r"[\\n;]+", search_url) if url.strip()]\n        return urls or [build_willhaben_url_for_area(profile, WILLHABEN_DEFAULT_AREA_ID)]\n    return build_willhaben_auto_urls(profile)\n\n\ndef resolve_search_url(profile: dict[str, object]) -> str:\n    return "\\n".join(resolve_search_urls(profile))\n\n'''
        text = text[:start] + new_block + text[end + 1:]

    # Add areaIds field to the create form.
    old_form = '''        <label>Willhaben-Suchergebnis-URL optional</label>\n        <input name="search_url" placeholder="leer lassen = automatische Willhaben-Suche über PLZ/areaIds">\n        <div class="grid">'''
    new_form = '''        <label>Willhaben-Suchergebnis-URL optional</label>\n        <input name="search_url" placeholder="leer lassen = automatische Willhaben-Suche über PLZ/areaIds">\n        <label>Willhaben PLZ / areaIds</label>\n        <input name="area_ids" value="8551" placeholder="z. B. 8551,8552,8544,8553">\n        <div class="grid">'''
    text = text.replace(old_form, new_form)

    old_form2 = '''        <label>Willhaben-Suchergebnis-URL optional</label>\n        <input name="search_url" placeholder="leer lassen = automatische Willhaben-Suche areaId=60351">\n        <div class="grid">'''
    text = text.replace(old_form2, new_form)

    old_form3 = '''        <label>Willhaben-Suchergebnis-URL optional</label>\n        <input name="search_url" placeholder="leer lassen = automatische Willhaben-Suche PLZ/areaId=8551">\n        <div class="grid">'''
    text = text.replace(old_form3, new_form)

    # Add area_ids parameter to create_profile form handler.
    text = text.replace('''    search_url: str | None = Form(None),\n    max_price_eur: str | None = Form(None),''', '''    search_url: str | None = Form(None),\n    area_ids: str | None = Form("8551"),\n    max_price_eur: str | None = Form(None),''')

    text = text.replace('''    else:\n        profile_data["search_url"] = build_willhaben_auto_url(profile_data)''', '''    else:\n        profile_data["search_url"] = "\\n".join(build_willhaben_auto_urls(profile_data, area_ids))''')

    # Replace run_search_profile to process multiple source URLs and dedupe links.
    start = text.find('async def run_search_profile(profile_id: str, max_results: int = 40) -> int:')
    end = text.find('\n\n@app.post("/search/profiles")', start)
    if start != -1 and end != -1:
        new_run = '''async def run_search_profile(profile_id: str, max_results: int = 40) -> int:\n    profile = get_search_profile(profile_id)\n    if not profile:\n        raise HTTPException(status_code=404, detail="Suchprofil nicht gefunden")\n\n    links: list[str] = []\n    seen_links: set[str] = set()\n    for search_url in resolve_search_urls(profile):\n        raw_html = await fetch_html(search_url)\n        for link in extract_listing_links(raw_html, search_url):\n            if link not in seen_links:\n                seen_links.add(link)\n                links.append(link)\n\n    links = links[: max(1, min(max_results, 120))]\n    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:\n        for link in links:\n            if source_url_exists(link):\n                upsert_search_candidate(profile_id, link, title_from_listing_url(link), status="imported")\n                continue\n            try:\n                detail = await client.get(link)\n                detail.raise_for_status()\n                parsed = parse_listing(link, detail.text)\n                status, reasons = evaluate_candidate(profile, parsed)\n                upsert_search_candidate(profile_id, link, parsed.title or title_from_listing_url(link), status=status, facts=facts_from_parsed(parsed), filter_reasons=reasons)\n            except Exception as exc:\n                upsert_search_candidate(profile_id, link, title_from_listing_url(link), status="review", filter_reasons=[f"Detailprüfung fehlgeschlagen: {str(exc)[:180]}"])\n    update_search_profile_run(profile_id, len(links))\n    return len(links)'''
        text = text[:start] + new_run + text[end:]

    # Display several generated source links in profile details.
    text = text.replace('''    source_url = resolve_search_url(profile)\n    body = f"""''', '''    source_urls = resolve_search_urls(profile)\n    source_links = "<br>".join(f'<a href="{esc(url)}" target="_blank">Willhaben-Suchquelle {idx}</a>' for idx, url in enumerate(source_urls, start=1))\n    body = f"""''')
    text = text.replace('''      <p class="muted"><a href="{esc(source_url)}" target="_blank">Willhaben-Suchquelle öffnen</a></p>''', '''      <p class="muted">{source_links}</p>''')

    MAIN_PATH.write_text(text, encoding="utf-8")


def migrate_existing_auto_urls():
    if not DB_PATH.exists():
        return
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("SELECT * FROM search_profiles").fetchall()
    except sqlite3.Error:
        con.close()
        return
    for row in rows:
        old_url = row["search_url"] or ""
        if "willhaben.at/iad/immobilien/haus-kaufen/haus-angebote" not in old_url:
            continue
        if "sfId=" in old_url or "lat=" in old_url or "lon=" in old_url:
            continue
        parts = urlsplit(old_url.splitlines()[0])
        params = dict(parse_qsl(parts.query, keep_blank_values=True))
        looks_auto = params.get("areaId") in {"60351", "8551"} or params.get("ESTATE_SIZE/LIVING_AREA_FROM") == "1200"
        if not looks_auto:
            continue
        new_url = build_url(row)
        if new_url != old_url:
            con.execute("UPDATE search_profiles SET search_url = ?, updated_at = datetime('now') WHERE id = ?", (new_url, row["id"]))
    con.commit()
    con.close()


patch_main()
migrate_existing_auto_urls()
PY

exec uvicorn app.main:app --host 0.0.0.0 --port 8088
