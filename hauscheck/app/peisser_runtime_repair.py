from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI

import app.immoscout_quality as quality
import app.immoscout_support as support
import app.peisser_support as peisser
import app.search_automation as search_automation
from app.storage import connect, list_houses, list_search_candidates


_PATCHED = False
_ORIGINAL_SYNC: Callable[[str], None] | None = None
_ORIGINAL_FIND = quality.find_probable_duplicate_conservative


def structured_match_peisser(house: dict[str, Any], parsed: Any) -> tuple[float, list[str]]:
    score, reasons = quality.structured_match_conservative(house, parsed)
    if support._close_number(house.get("price_eur"), parsed.price_eur, 0.015, 2500.0):
        score += 1.5
        reasons.append("gleicher Angebotspreis")
    return score, reasons


async def find_probable_duplicate_peisser(parsed: Any) -> tuple[dict[str, Any] | None, str | None, float, dict[str, Any]]:
    if str(getattr(parsed, "source_name", "") or "") != peisser.PEISSER_SOURCE:
        return await _ORIGINAL_FIND(parsed)

    incoming_hashes = await support._remote_image_hashes(parsed.image_urls, 5) if parsed.image_urls else []
    best: tuple[dict[str, Any] | None, str | None, float, dict[str, Any]] = (None, None, 0.0, {})

    for house in list_houses():
        structured_score, reasons = structured_match_peisser(house, parsed)
        existing_hashes = support._local_media_hashes(str(house.get("id")), 12) if incoming_hashes else []
        image_matches = support._image_match_count(incoming_hashes, existing_hashes)
        method: str | None = None
        confidence = structured_score

        exact_address = "identische bestätigte Adresse" in reasons
        strong_core = all(
            marker in reasons
            for marker in ("gleicher Ort/PLZ", "gleiche Wohnfläche", "gleiche Grundstücksfläche", "gleiche Zimmerzahl")
        )
        corroborating_markers = {
            marker
            for marker in ("gleiches Baujahr", "gleicher HWB", "gleiche Heizungsart", "gleicher Angebotspreis")
            if marker in reasons
        }
        strong_title = any(reason.startswith("sehr ähnlicher Titel") for reason in reasons)

        if image_matches >= 2:
            method = "perceptual_images"
            confidence = 20.0 + image_matches
        elif image_matches >= 1 and structured_score >= 4.0 and "gleicher Ort/PLZ" in reasons:
            method = "image_plus_facts"
            confidence = 15.0 + structured_score
        elif exact_address and structured_score >= 10.0:
            method = "exact_address"
            confidence = structured_score
        elif strong_core and len(corroborating_markers) >= 2 and structured_score >= 9.0:
            # Peisser often uses completely different marketing titles and older portal images
            # may no longer be downloadable. Four matching core facts plus at least two
            # independent technical/price facts are sufficiently specific for one house.
            method = "structured_facts"
            confidence = structured_score
        elif strong_core and corroborating_markers and strong_title and structured_score >= 9.0:
            method = "structured_facts"
            confidence = structured_score

        details = {
            "structured_score": structured_score,
            "reasons": reasons,
            "image_matches": image_matches,
            "corroborating_facts": sorted(corroborating_markers),
            "automatic_merge": bool(method),
        }
        if method and confidence > best[2]:
            best = (house, method, confidence, details)

    return best


def sync_candidate_metadata_portal(profile_id: str) -> None:
    if _ORIGINAL_SYNC:
        _ORIGINAL_SYNC(profile_id)

    with connect() as con:
        for candidate in list_search_candidates(profile_id):
            source_url = str(candidate.get("source_url") or "")
            con.execute(
                """
                UPDATE search_candidates
                SET provider = ?, external_id = ?, canonical_url = ?
                WHERE id = ?
                """,
                (
                    support.provider_for_url(source_url),
                    support.external_id_for_url(source_url),
                    support.canonical_listing_url(source_url),
                    candidate.get("id"),
                ),
            )
        con.commit()


def repair_existing_peisser_profiles() -> None:
    with connect() as con:
        con.execute(
            """
            UPDATE search_profiles
            SET source_name = ?, search_url_mode = 'automatic', search_url = ?
            WHERE LOWER(COALESCE(search_url, '')) LIKE '%peisser-immobilien.at%'
              AND COALESCE(source_name, '') <> ?
            """,
            (peisser.PEISSER_SOURCE, peisser.PEISSER_SEARCH_URL, peisser.PEISSER_SOURCE),
        )
        con.commit()


def register_peisser_runtime_repair(app: FastAPI) -> None:
    global _PATCHED, _ORIGINAL_SYNC
    if _PATCHED:
        return

    repair_existing_peisser_profiles()
    _ORIGINAL_SYNC = search_automation.sync_candidate_metadata
    support.find_probable_duplicate = find_probable_duplicate_peisser
    quality.find_probable_duplicate_conservative = find_probable_duplicate_peisser
    search_automation.sync_candidate_metadata = sync_candidate_metadata_portal
    _PATCHED = True
