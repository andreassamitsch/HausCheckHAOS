from __future__ import annotations

import re
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from fastapi import FastAPI

import app.immoscout_dynamic_search as dynamic
import app.immoscout_support as support
import app.main as main
import app.modern_ui as modern_ui
import app.search_lifecycle_ui as lifecycle_ui
from app.storage import connect, now_iso, row_to_dict


_PATCHED = False
_ORIGINAL_PROFILE_FORM: Callable[..., str] = dynamic._profile_form

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
BROWSER_HEADERS = {
    "User-Agent": BROWSER_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "de-AT,de;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}
INTEGER_QUERY_KEYS = {"plotAreaFrom", "primaryAreaFrom", "primaryPriceTo"}


def integer_parameter(value: object, fallback: float) -> str:
    """ImmobilienScout expects these filter parameters as whole numbers."""
    try:
        number = float(str(value).replace(",", "."))
    except Exception:
        number = float(fallback)
    return str(max(0, int(round(number))))


def build_immoscout_url_integer(profile: dict[str, Any], area_id: str) -> str:
    params = [
        ("plotAreaFrom", integer_parameter(profile.get("min_plot_area_m2") or 700, 700)),
        ("primaryAreaFrom", integer_parameter(profile.get("min_living_area_m2") or 120, 120)),
        ("primaryPriceTo", integer_parameter(profile.get("max_price_eur") or profile.get("soft_max_price_eur") or 420000, 420000)),
    ]
    return f"https://www.immobilienscout24.at/regional/{area_id}/haus-kaufen?{urlencode(params)}"


def build_immoscout_auto_urls_integer(profile: dict[str, Any], area_ids: object | None = None) -> list[str]:
    return [build_immoscout_url_integer(profile, area) for area in dynamic.parse_search_areas(area_ids)]


def normalize_immoscout_url(url: str) -> str:
    if not support.is_immoscout_url(url):
        return url
    parts = urlsplit(url)
    query: list[tuple[str, str]] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key in INTEGER_QUERY_KEYS:
            try:
                value = str(int(round(float(value.replace(",", ".")))))
            except Exception:
                pass
        query.append((key, value))
    return urlunsplit((parts.scheme or "https", parts.netloc, parts.path, urlencode(query), parts.fragment))


def normalize_automatic_profiles() -> int:
    changed = 0
    with connect() as con:
        rows = con.execute("SELECT * FROM search_profiles WHERE source_name = ?", (support.IMMOSCOUT_SOURCE,)).fetchall()
        for row in rows:
            profile = row_to_dict(row) or {}
            if str(profile.get("search_url_mode") or "automatic") != "automatic":
                continue
            areas = dynamic._areas_from_profile(profile)
            resolved = "\n".join(build_immoscout_auto_urls_integer(profile, areas))
            if str(profile.get("search_url") or "") == resolved:
                continue
            con.execute(
                "UPDATE search_profiles SET search_url = ?, updated_at = ?, last_run_status = ?, last_error = NULL WHERE id = ?",
                (resolved, now_iso(), "ImmobilienScout-URL auf Ganzzahlen normalisiert", profile["id"]),
            )
            changed += 1
        con.commit()
    return changed


def _profile_form_integer(profile: dict[str, Any] | None = None, action: str = "") -> str:
    html = _ORIGINAL_PROFILE_FORM(profile, action)

    # Existing SQLite REAL values render as 700.0/120.0. Display whole values for these portal filters.
    for field_name in ("min_living_area_m2", "min_plot_area_m2", "max_price_eur", "soft_max_price_eur"):
        pattern = rf'(name="{field_name}"[^>]*value=")([0-9]+)\.0("[^>]*>)'
        html = re.sub(pattern, lambda match: match.group(1) + match.group(2) + match.group(3), html)

    old = """        const maxPrice = field('max_price_eur').value || field('soft_max_price_eur').value || '420000';
        const living = field('min_living_area_m2').value || '120';
        const plot = field('min_plot_area_m2').value || '700';"""
    new = """        const whole = (value, fallback) => {
          const parsed = Number(String(value || fallback).replace(',', '.'));
          return Number.isFinite(parsed) ? String(Math.round(parsed)) : String(fallback);
        };
        const maxPrice = whole(field('max_price_eur').value || field('soft_max_price_eur').value, 420000);
        const living = whole(field('min_living_area_m2').value, 120);
        const plot = whole(field('min_plot_area_m2').value, 700);"""
    return html.replace(old, new)


async def fetch_html_browser(url: str) -> str:
    async with httpx.AsyncClient(timeout=45, follow_redirects=True, headers=BROWSER_HEADERS) as client:
        response = await client.get(normalize_immoscout_url(url))
        response.raise_for_status()
        return response.text


def register_immoscout_url_runtime_fix(app: FastAPI) -> None:
    global _PATCHED
    if _PATCHED:
        return

    dynamic._number_text = integer_parameter
    dynamic.build_immoscout_url_for_area = build_immoscout_url_integer
    dynamic.build_immoscout_auto_urls = build_immoscout_auto_urls_integer
    dynamic._profile_form = _profile_form_integer

    # All active UI references must use the same form renderer.
    modern_ui._profile_form = _profile_form_integer
    lifecycle_ui._new_profile_form = lambda: _profile_form_integer(None, "profiles")
    support._profile_form_html = lambda: _profile_form_integer(None, "profiles")

    main.USER_AGENT = BROWSER_USER_AGENT
    main.fetch_html = fetch_html_browser

    normalize_automatic_profiles()
    _PATCHED = True
