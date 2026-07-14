from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

import app.focused_ui as focused_ui
import app.immoscout_support as support
import app.search_lifecycle_ui as lifecycle_ui


_PATCHED = False


def _normalize_heating(value: object) -> set[str]:
    text = support._normalize_text(value)
    result: set[str] = set()
    groups = {
        "gas": ("gas", "gasheizung", "erdgas"),
        "oil": ("oel", "oil", "heizoel"),
        "wood": ("holz", "pellet", "biomasse", "hackgut"),
        "heatpump": ("waermepumpe", "luftwaermepumpe", "erdwaermepumpe"),
        "district": ("fernwaerme", "nahwaerme"),
        "electric": ("strom", "elektro", "nachtspeicher"),
    }
    for canonical, markers in groups.items():
        if any(marker in text for marker in markers):
            result.add(canonical)
    return result


def structured_match_conservative(house: dict[str, Any], parsed: Any) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    existing_location = support._location_key(house.get("location_text"))
    parsed_location = support._location_key(parsed.location_text)
    if existing_location and parsed_location and existing_location == parsed_location:
        score += 1.0
        reasons.append("gleicher Ort/PLZ")

    exact_existing = str(house.get("address_status") or "") == "exact"
    exact_new = parsed.address_status == "exact"
    if exact_existing and exact_new and support._normalize_text(house.get("location_text")) == support._normalize_text(parsed.location_text):
        score += 10.0
        reasons.append("identische bestätigte Adresse")

    if support._close_number(house.get("living_area_m2"), parsed.living_area_m2, 0.025, 2.0):
        score += 2.0
        reasons.append("gleiche Wohnfläche")
    if support._close_number(house.get("plot_area_m2"), parsed.plot_area_m2, 0.025, 12.0):
        score += 2.0
        reasons.append("gleiche Grundstücksfläche")
    if support._close_number(house.get("rooms"), parsed.rooms, 0.0, 0.1):
        score += 1.0
        reasons.append("gleiche Zimmerzahl")
    if house.get("year_built") and parsed.year_built and int(house["year_built"]) == int(parsed.year_built):
        score += 1.0
        reasons.append("gleiches Baujahr")
    if support._close_number(house.get("energy_hwb"), parsed.energy_hwb, 0.015, 2.0):
        score += 1.0
        reasons.append("gleicher HWB")

    existing_heating = _normalize_heating(house.get("heating"))
    parsed_heating = _normalize_heating(parsed.heating)
    if existing_heating and parsed_heating and existing_heating.intersection(parsed_heating):
        score += 1.0
        reasons.append("gleiche Heizungsart")

    similarity = support._title_similarity(house.get("title"), parsed.title)
    if similarity >= 0.78:
        score += 2.0
        reasons.append(f"sehr ähnlicher Titel {similarity:.2f}")
    elif similarity >= 0.64:
        score += 0.5
        reasons.append(f"ähnlicher Titel {similarity:.2f}")
    return score, reasons


async def find_probable_duplicate_conservative(parsed: Any) -> tuple[dict[str, Any] | None, str | None, float, dict[str, Any]]:
    from app.storage import list_houses

    incoming_hashes = await support._remote_image_hashes(parsed.image_urls, 5) if parsed.image_urls else []
    best: tuple[dict[str, Any] | None, str | None, float, dict[str, Any]] = (None, None, 0.0, {})
    for house in list_houses():
        structured_score, reasons = structured_match_conservative(house, parsed)
        existing_hashes = support._local_media_hashes(str(house.get("id")), 12) if incoming_hashes else []
        image_matches = support._image_match_count(incoming_hashes, existing_hashes)
        method: str | None = None
        confidence = structured_score

        exact_address = "identische bestätigte Adresse" in reasons
        strong_core = all(
            marker in reasons
            for marker in ("gleicher Ort/PLZ", "gleiche Wohnfläche", "gleiche Grundstücksfläche", "gleiche Zimmerzahl")
        )
        corroborating = any(
            marker in reasons
            for marker in ("gleiches Baujahr", "gleicher HWB", "gleiche Heizungsart")
        )
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
        elif strong_core and corroborating and strong_title and structured_score >= 9.0:
            method = "structured_facts"
            confidence = structured_score

        details = {
            "structured_score": structured_score,
            "reasons": reasons,
            "image_matches": image_matches,
            "automatic_merge": bool(method),
        }
        if method and confidence > best[2]:
            best = (house, method, confidence, details)
    return best


def _wrap_layout(original: Callable[..., HTMLResponse]) -> Callable[..., HTMLResponse]:
    if getattr(original, "_portal_labels_patched", False):
        return original

    def portal_layout(title: str, body: str, home_href: str = "./") -> HTMLResponse:
        body = body.replace("Willhaben wird durchsucht", "Immobilienportale werden durchsucht")
        body = body.replace("Willhaben-Suchquelle", "Portal-Suchquelle")
        body = body.replace("Bei Willhaben öffnen", "Inserat öffnen")
        response = original(title, body, home_href)
        return response

    setattr(portal_layout, "_portal_labels_patched", True)
    return portal_layout


def register_immoscout_quality(app: FastAPI) -> None:
    global _PATCHED
    if _PATCHED:
        return
    support._structured_match = structured_match_conservative
    support.find_probable_duplicate = find_probable_duplicate_conservative
    focused_ui.layout = _wrap_layout(focused_ui.layout)
    lifecycle_ui.layout = _wrap_layout(lifecycle_ui.layout)
    _PATCHED = True
