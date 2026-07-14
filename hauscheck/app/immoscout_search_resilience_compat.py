from __future__ import annotations

from fastapi import FastAPI

import app.immoscout_search_resilience as resilience
import app.immoscout_support as support
import app.main as main
import app.parser as parser_module


_PATCHED = False


def extract_listing_links_compatible(raw_html: str, base_url: str) -> list[str]:
    if support.is_immoscout_url(base_url):
        return sorted(
            candidate.url
            for candidate in resilience.extract_immoscout_candidates_resilient(raw_html, base_url)
        )
    if support._ORIGINAL_EXTRACT_CANDIDATES:
        return sorted(
            candidate.url
            for candidate in support._ORIGINAL_EXTRACT_CANDIDATES(raw_html, base_url)
        )
    return []


def register_immoscout_search_resilience_compat(app: FastAPI) -> None:
    global _PATCHED
    if _PATCHED:
        return

    # Hydration payloads often contain an unused resultCount=0 template. Only visible
    # no-result wording is accepted as proof that a search is genuinely empty.
    resilience.EMPTY_MARKERS = (
        "keine passenden immobilien",
        "keine ergebnisse gefunden",
        "leider konnten wir keine",
        "0 treffer gefunden",
        "keine immobilien entsprechen",
    )

    resilience.extract_listing_links_resilient = extract_listing_links_compatible
    main.extract_listing_links = extract_listing_links_compatible
    parser_module.extract_listing_links = extract_listing_links_compatible

    _PATCHED = True
