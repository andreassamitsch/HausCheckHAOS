from __future__ import annotations

import html as html_lib
import json
import re
from dataclasses import asdict
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException

import app.immoscout_support as support
import app.main as main
import app.parser as parser_module
import app.search_automation as search_automation
from app.parser import SearchResultCandidate
from app.storage import (
    get_search_profile,
    source_url_exists,
    update_search_profile_run,
    upsert_search_candidate,
)


_PATCHED = False

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 16; SM-S911B) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "de-AT,de;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
}

DESKTOP_HEADERS = {
    **BROWSER_HEADERS,
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
}

CRAWLER_HEADERS = {
    **BROWSER_HEADERS,
    "User-Agent": (
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    ),
}

BLOCK_MARKERS = (
    "captcha",
    "access denied",
    "forbidden",
    "unusual traffic",
    "verify you are human",
    "security check",
    "bot detection",
    "cloudflare",
    "datadome",
    "consent required",
)

EMPTY_MARKERS = (
    "keine passenden immobilien",
    "keine ergebnisse gefunden",
    "leider konnten wir keine",
    "0 treffer",
    '"resultcount":0',
    '"totalcount":0',
)


def _decode_variants(raw_html: str) -> list[str]:
    """Return common representations used by server-rendered and hydrated JS pages."""
    variants: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        if value and value not in seen:
            seen.add(value)
            variants.append(value)

    add(raw_html)
    add(html_lib.unescape(raw_html))
    index = 0
    while index < len(variants) and len(variants) < 12:
        value = variants[index]
        index += 1
        decoded = value
        replacements = {
            r"\u002F": "/",
            r"\u002f": "/",
            r"\u003A": ":",
            r"\u003a": ":",
            r"\u0026": "&",
            r"\u003D": "=",
            r"\u003d": "=",
            r"\u002D": "-",
            r"\u002d": "-",
            r"\x2F": "/",
            r"\x2f": "/",
            r"\/": "/",
        }
        for encoded, plain in replacements.items():
            decoded = decoded.replace(encoded, plain)
        add(decoded)
        try:
            add(unquote(decoded))
        except Exception:
            pass
    return variants


def _candidate_key(candidate: SearchResultCandidate) -> str:
    return support.external_id_for_url(candidate.url) or support.canonical_listing_url(candidate.url)


def extract_immoscout_candidates_resilient(raw_html: str, base_url: str) -> list[SearchResultCandidate]:
    by_key: dict[str, SearchResultCandidate] = {}

    def add_url(raw_url: str, title: str | None = None, preview: str | None = None) -> None:
        value = html_lib.unescape(str(raw_url or "")).replace("\\/", "/").strip()
        if not value:
            return
        absolute = urljoin(base_url, value)
        expose_id = support.external_id_for_url(absolute)
        if not expose_id:
            return
        candidate = SearchResultCandidate(
            url=support.canonical_listing_url(absolute),
            title=(str(title).strip() if title else None),
            preview_image_url=(str(preview).strip() if preview else None),
        )
        key = _candidate_key(candidate)
        current = by_key.get(key)
        if current is None:
            by_key[key] = candidate
        else:
            if candidate.title and not current.title:
                current.title = candidate.title
            if candidate.preview_image_url and not current.preview_image_url:
                current.preview_image_url = candidate.preview_image_url

    # First use the structured parser already proven for the normal HTML response.
    for candidate in support.extract_immoscout_candidates(raw_html, base_url):
        by_key[_candidate_key(candidate)] = candidate

    variants = _decode_variants(raw_html)
    expose_patterns = (
        r"(?:https?://(?:www\.)?immobilienscout24\.at)?/expose/([A-Za-z0-9_-]{8,64})",
        r"(?:https?%3A%2F%2F(?:www\.)?immobilienscout24\.at)?%2Fexpose%2F([A-Za-z0-9_-]{8,64})",
    )
    id_patterns = (
        r'["\'](?:exposeId|expose_id|listingId|listing_id|propertyId)["\']\s*:\s*["\']([A-Za-z0-9_-]{16,64})["\']',
        r'data-(?:expose|listing|property)-id=["\']([A-Za-z0-9_-]{8,64})["\']',
    )

    for variant in variants:
        for pattern in expose_patterns:
            for match in re.finditer(pattern, variant, re.I):
                add_url(f"https://www.immobilienscout24.at/expose/{match.group(1)}")
        for pattern in id_patterns:
            for match in re.finditer(pattern, variant, re.I):
                add_url(f"https://www.immobilienscout24.at/expose/{match.group(1)}")

    # JSON hydration scripts may hide URLs several levels deep.
    soup = BeautifulSoup(raw_html, "html.parser")

    def walk(value: Any, key_name: str = "") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, str(key))
        elif isinstance(value, list):
            for child in value:
                walk(child, key_name)
        elif isinstance(value, str):
            decoded_values = _decode_variants(value)
            for decoded in decoded_values:
                if "/expose/" in decoded:
                    for match in re.finditer(r"/expose/([A-Za-z0-9_-]{8,64})", decoded, re.I):
                        add_url(f"https://www.immobilienscout24.at/expose/{match.group(1)}")
                elif key_name.lower() in {"exposeid", "expose_id", "listingid", "listing_id", "propertyid"}:
                    if re.fullmatch(r"[A-Za-z0-9_-]{8,64}", decoded):
                        add_url(f"https://www.immobilienscout24.at/expose/{decoded}")

    for script in soup.find_all("script"):
        payload_text = script.string or script.get_text() or ""
        if not payload_text or len(payload_text) > 12_000_000:
            continue
        for variant in _decode_variants(payload_text)[:4]:
            stripped = variant.strip()
            if not stripped or stripped[0] not in "[{":
                continue
            try:
                walk(json.loads(stripped))
                break
            except Exception:
                continue

    return list(by_key.values())


def extract_listing_links_resilient(raw_html: str, base_url: str) -> list[str]:
    if support.is_immoscout_url(base_url):
        return sorted(candidate.url for candidate in extract_immoscout_candidates_resilient(raw_html, base_url))
    return main.extract_listing_links(raw_html, base_url)


def _page_flags(raw_html: str) -> dict[str, Any]:
    lower = raw_html.lower()
    return {
        "bytes": len(raw_html.encode("utf-8", errors="ignore")),
        "blocked": [marker for marker in BLOCK_MARKERS if marker in lower][:3],
        "explicit_empty": any(marker in lower for marker in EMPTY_MARKERS),
        "literal_expose": lower.count("/expose/"),
        "unicode_expose": lower.count("\\u002fexpose\\u002f"),
        "encoded_expose": lower.count("%2fexpose%2f"),
    }


async def _fetch_search_attempt(url: str, headers: dict[str, str], *, warmup: bool) -> tuple[str, str, int, dict[str, Any]]:
    async with httpx.AsyncClient(timeout=45, follow_redirects=True, headers=headers) as client:
        if warmup:
            try:
                await client.get("https://www.immobilienscout24.at/", headers={**headers, "Sec-Fetch-Site": "none"})
            except Exception:
                pass
        request_headers = dict(headers)
        request_headers["Referer"] = "https://www.immobilienscout24.at/"
        response = await client.get(url, headers=request_headers)
        response.raise_for_status()
        text = response.text
        flags = _page_flags(text)
        flags["content_type"] = response.headers.get("content-type")
        return text, str(response.url), response.status_code, flags


async def fetch_immoscout_search(url: str) -> tuple[str, str, list[SearchResultCandidate], list[dict[str, Any]]]:
    attempts = [
        ("mobile-session", BROWSER_HEADERS, True),
        ("desktop-session", DESKTOP_HEADERS, True),
        ("desktop-direct", DESKTOP_HEADERS, False),
        ("crawler-direct", CRAWLER_HEADERS, False),
    ]
    diagnostics: list[dict[str, Any]] = []
    best_html = ""
    best_url = url
    best_candidates: list[SearchResultCandidate] = []

    for label, headers, warmup in attempts:
        try:
            raw_html, final_url, status, flags = await _fetch_search_attempt(url, headers, warmup=warmup)
            candidates = extract_immoscout_candidates_resilient(raw_html, final_url)
            entry = {"attempt": label, "status": status, "final_url": final_url, "candidates": len(candidates), **flags}
            diagnostics.append(entry)
            if len(raw_html) > len(best_html):
                best_html, best_url = raw_html, final_url
            if len(candidates) > len(best_candidates):
                best_candidates = candidates
                best_html, best_url = raw_html, final_url
            if candidates:
                return raw_html, final_url, candidates, diagnostics
        except Exception as exc:
            diagnostics.append({"attempt": label, "error": str(exc)[:300], "candidates": 0})

    return best_html, best_url, best_candidates, diagnostics


def _diagnostic_text(items: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in items:
        label = str(item.get("attempt") or item.get("url") or "Abruf")
        if item.get("error"):
            parts.append(f"{label}: Fehler {item['error']}")
            continue
        parts.append(
            f"{label}: HTTP {item.get('status')} · {item.get('bytes', 0)} Bytes · "
            f"{item.get('candidates', 0)} Exposés"
            + (f" · Blockhinweis {','.join(item.get('blocked') or [])}" if item.get("blocked") else "")
        )
    return " | ".join(parts)[:1800]


async def run_search_profile_resilient(profile_id: str, max_results: int = 80) -> int:
    profile = get_search_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Suchprofil nicht gefunden")

    links: list[str] = []
    seen_keys: set[str] = set()
    run_diagnostics: list[dict[str, Any]] = []
    explicit_empty_pages = 0
    immoscout_pages = 0

    for search_url in main.resolve_search_urls(profile):
        if support.is_immoscout_url(search_url):
            immoscout_pages += 1
            raw_html, final_url, candidates, diagnostics = await fetch_immoscout_search(search_url)
            run_diagnostics.extend({"url": search_url, **item} for item in diagnostics)
            if raw_html and _page_flags(raw_html).get("explicit_empty"):
                explicit_empty_pages += 1
            page_links = [candidate.url for candidate in candidates]
        else:
            raw_html = await main.fetch_html(search_url)
            final_url = search_url
            page_links = main.extract_listing_links(raw_html, final_url)

        for link in page_links:
            key = main.listing_key(link)
            if key not in seen_keys:
                seen_keys.add(key)
                links.append(link)

    links = links[: max(1, min(int(max_results or 80), 160))]

    if immoscout_pages and not links and explicit_empty_pages < immoscout_pages:
        message = "ImmobilienScout lieferte keine auslesbaren Exposé-Links. " + _diagnostic_text(run_diagnostics)
        raise RuntimeError(message)

    async with httpx.AsyncClient(timeout=45, follow_redirects=True, headers=DESKTOP_HEADERS) as client:
        for link in links:
            if source_url_exists(link):
                upsert_search_candidate(profile_id, link, main.title_from_listing_url(link), status="imported")
                continue
            try:
                detail = await client.get(link, headers={**DESKTOP_HEADERS, "Referer": "https://www.immobilienscout24.at/"})
                detail.raise_for_status()
                parsed = main.parse_listing(link, detail.text)
                status, reasons = main.evaluate_candidate(profile, parsed)
                upsert_search_candidate(
                    profile_id,
                    link,
                    parsed.title or main.title_from_listing_url(link),
                    status=status,
                    facts=main.facts_from_parsed(parsed),
                    filter_reasons=reasons,
                )
            except Exception as exc:
                upsert_search_candidate(
                    profile_id,
                    link,
                    main.title_from_listing_url(link),
                    status="review",
                    filter_reasons=[f"Detailprüfung fehlgeschlagen: {str(exc)[:180]}"],
                )

    update_search_profile_run(profile_id, len(links))
    return len(links)


def register_immoscout_search_resilience(app: FastAPI) -> None:
    global _PATCHED
    if _PATCHED:
        return

    # Search and parser references are patched last so every manual and scheduled route uses them.
    parser_module.extract_listing_candidates = support.extract_listing_candidates_multi
    parser_module.extract_listing_links = extract_listing_links_resilient
    main.extract_listing_links = extract_listing_links_resilient
    main.run_search_profile = run_search_profile_resilient
    search_automation.run_search_profile = run_search_profile_resilient

    _PATCHED = True
