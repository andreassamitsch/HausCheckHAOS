from __future__ import annotations

from typing import Any, Callable

import httpx
from fastapi import FastAPI, HTTPException
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


async def download_pending_media_portal(house_id: str, limit: int = 120) -> None:
    import app.main as main_module
    from app.storage import find_media_by_hash, get_house, list_media, project_dir, update_media

    if not get_house(house_id):
        raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")

    portal_items = [
        item
        for item in list_media(house_id)
        if item.get("download_status") == "pending"
        and item.get("kind") == "image"
        and item.get("original_url")
        and support.IMMOSCOUT_IMAGE_HOST in support._host(str(item.get("original_url")))
    ][:limit]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "de-AT,de;q=0.9,en;q=0.7",
        "Referer": "https://www.immobilienscout24.at/",
    }
    hdir = project_dir(house_id)
    async with httpx.AsyncClient(timeout=35, follow_redirects=True, headers=headers) as client:
        for item in portal_items:
            try:
                url = str(item["original_url"])
                response = await client.get(url)
                response.raise_for_status()
                content = response.content
                meta = main_module.image_meta(content)
                if main_module.is_too_small_for_gallery(meta.get("width"), meta.get("height")):
                    update_media(
                        str(item["id"]),
                        {
                            **meta,
                            "mime_type": response.headers.get("content-type"),
                            "download_status": "skipped",
                            "download_error": f"zu kleines Bild / vermutlich Logo oder UI-Grafik ({meta.get('width')}x{meta.get('height')})",
                        },
                    )
                    continue
                duplicate = find_media_by_hash(house_id, "image", str(meta["content_hash"]))
                if duplicate and duplicate.get("id") != item.get("id"):
                    update_media(
                        str(item["id"]),
                        {
                            **meta,
                            "mime_type": response.headers.get("content-type"),
                            "download_status": "skipped",
                            "download_error": f"Duplikat von Medium {duplicate.get('id')}",
                        },
                    )
                    continue
                fallback_name = f"{item['id']}.jpg"
                safe_name = main_module.safe_filename_from_url(url, fallback_name)
                filename = f"{item['id']}_{safe_name}"
                target = hdir / "images" / filename
                target.write_bytes(content)
                update_media(
                    str(item["id"]),
                    {
                        **meta,
                        "local_path": str(target),
                        "mime_type": response.headers.get("content-type") or "image/jpeg",
                        "download_status": "downloaded",
                        "download_error": None,
                    },
                )
            except Exception as exc:
                update_media(str(item["id"]), {"download_status": "failed", "download_error": str(exc)[:500]})

    if support._ORIGINAL_DOWNLOAD_MEDIA:
        await support._ORIGINAL_DOWNLOAD_MEDIA(house_id, limit)
    support.dedupe_house_images_perceptually(house_id)


def _wrap_layout(original: Callable[..., HTMLResponse]) -> Callable[..., HTMLResponse]:
    if getattr(original, "_portal_labels_patched", False):
        return original

    def portal_layout(title: str, body: str, home_href: str = "./") -> HTMLResponse:
        body = body.replace("Willhaben wird durchsucht", "Immobilienportale werden durchsucht")
        body = body.replace("Willhaben-Suchquelle", "Portal-Suchquelle")
        body = body.replace("Bei Willhaben öffnen", "Inserat öffnen")
        return original(title, body, home_href)

    setattr(portal_layout, "_portal_labels_patched", True)
    return portal_layout


def register_immoscout_quality(app: FastAPI) -> None:
    global _PATCHED
    if _PATCHED:
        return
    import app.import_patch as import_patch
    import app.main as main_module

    support._structured_match = structured_match_conservative
    support.find_probable_duplicate = find_probable_duplicate_conservative
    support.download_pending_media_enhanced = download_pending_media_portal
    main_module.download_pending_media_files = download_pending_media_portal
    import_patch.download_pending_media_files = download_pending_media_portal
    focused_ui.layout = _wrap_layout(focused_ui.layout)
    lifecycle_ui.layout = _wrap_layout(lifecycle_ui.layout)
    _PATCHED = True
