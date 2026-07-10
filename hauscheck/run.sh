#!/usr/bin/env sh
set -eu

DATA_DIR="${HAUSCHECK_DATA_DIR:-/share/hauscheck}"
mkdir -p "${DATA_DIR}"
mkdir -p "${DATA_DIR}/projects"
mkdir -p "${DATA_DIR}/logs"

export HAUSCHECK_DATA_DIR="${DATA_DIR}"
export PYTHONUNBUFFERED=1

# v0.4.3 hotfix:
# Willhaben supports postal-code searches via areaId, e.g. Wies = 8551.
# Older auto-generated profiles used areaId=60351. Existing auto profiles are
# migrated to the better postal-code URL on start. Manual radius URLs with
# sfId/lat/lon are left untouched.
python3 - <<'PY'
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

DATA_DIR = Path(os.environ.get("HAUSCHECK_DATA_DIR", "/share/hauscheck"))
DB_PATH = DATA_DIR / "hauscheck.db"
MAIN_PATH = Path("/app/app/main.py")
WILLHABEN_BASE = "https://www.willhaben.at/iad/immobilien/haus-kaufen/haus-angebote"
DEFAULT_AREA_ID = "8551"


def numeric(value, default):
    if value is None or str(value).strip() == "":
        return default
    try:
        return int(float(str(value).replace(" ", "").replace(",", ".")))
    except Exception:
        return default


def build_url(row):
    price = numeric(row["max_price_eur"] if row["max_price_eur"] is not None else row["soft_max_price_eur"], 400000)
    living = numeric(row["min_living_area_m2"], 120)
    query = urlencode({
        "areaId": DEFAULT_AREA_ID,
        "page": 1,
        "PRICE_TO": price,
        "ESTATE_SIZE/LIVING_AREA_FROM": living,
    })
    return f"{WILLHABEN_BASE}?{query}"


def patch_main_defaults():
    if not MAIN_PATH.exists():
        return
    text = MAIN_PATH.read_text(encoding="utf-8")
    text = text.replace('WILLHABEN_DEFAULT_AREA_ID = "60351"', 'WILLHABEN_DEFAULT_AREA_ID = "8551"')
    text = text.replace('app = FastAPI(title=APP_NAME, version="0.4.2")', 'app = FastAPI(title=APP_NAME, version="0.4.3")')
    text = text.replace('v0.4.2: Zahlenparser-Fix für Wohnfläche/Preis aus SQLite.', 'v0.4.3: Willhaben nutzt PLZ areaId=8551 als Standardquelle.')
    text = text.replace('leer lassen = automatische Willhaben-Suche areaId=60351', 'leer lassen = automatische Willhaben-Suche PLZ/areaId=8551')
    text = text.replace('Automatische Willhaben-Quelle: areaId=60351, sort=1, rows=30, page=1, PRICE_TO und ESTATE_SIZE/LIVING_AREA_FROM aus den Kriterien.', 'Automatische Willhaben-Quelle: areaId=8551, page=1, PRICE_TO und ESTATE_SIZE/LIVING_AREA_FROM aus den Kriterien.')
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
        parts = urlsplit(old_url)
        params = dict(parse_qsl(parts.query, keep_blank_values=True))
        looks_auto = params.get("areaId") in {"60351", "8551"} or params.get("ESTATE_SIZE/LIVING_AREA_FROM") == "1200"
        if not looks_auto:
            continue
        new_url = build_url(row)
        if new_url != old_url:
            con.execute("UPDATE search_profiles SET search_url = ?, updated_at = datetime('now') WHERE id = ?", (new_url, row["id"]))
    con.commit()
    con.close()


patch_main_defaults()
migrate_existing_auto_urls()
PY

exec uvicorn app.main:app --host 0.0.0.0 --port 8088
