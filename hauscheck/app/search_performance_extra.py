from __future__ import annotations

import asyncio
import copy
import hashlib
import time
from typing import Any, Awaitable, Callable

import httpx

import app.immoscout_quality as quality
import app.immoscout_support as support
import app.import_patch as import_patch
import app.main as main
import app.peisser_runtime_repair as peisser_repair
import app.peisser_support as peisser
import app.search_automation as search_automation
import app.search_performance as performance
from app.storage import list_houses, list_media, list_search_profiles

_PATCHED = False
_ORIGINAL_PEISSER_BUNDLE: Callable[[str], Awaitable[str]] | None = None
_ORIGINAL_PEISSER_PARSE: Callable[[str, str], Any] | None = None
_ORIGINAL_FIND_DUPLICATE: Callable[[Any], Awaitable[tuple[dict[str, Any] | None, str | None, float, dict[str, Any]]]] | None = None


def _cache_key(prefix: str, url: str, raw_html: str = "") -> str:
    canonical = support.canonical_listing_url(url)
    if raw_html:
        digest = hashlib.sha256(raw_html.encode("utf-8", errors="ignore")).hexdigest()
        return f"{prefix}:{canonical}|{digest}"
    return f"{prefix}:{canonical}"


async def peisser_bundle_cached(url: str) -> str:
    if _ORIGINAL_PEISSER_BUNDLE is None:
        raise RuntimeError("Peisser-Abruf ist noch nicht registriert")
    key = _cache_key("peisser-bundle", url)
    current = performance._HTML_CACHE.get(key)
    if current and time.monotonic() - current[0] <= performance.HTML_CACHE_TTL_DETAIL:
        performance._HTML_CACHE.move_to_end(key)
        performance._stat("peisser_bundle_cache_hits")
        return current[1]

    lock = performance._FETCH_LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        current = performance._HTML_CACHE.get(key)
        if current and time.monotonic() - current[0] <= performance.HTML_CACHE_TTL_DETAIL:
            performance._HTML_CACHE.move_to_end(key)
            performance._stat("peisser_bundle_cache_hits")
            return current[1]
        try:
            raw_html = await _ORIGINAL_PEISSER_BUNDLE(url)
        except httpx.HTTPStatusError as exc:
            if not 500 <= int(exc.response.status_code) <= 599:
                raise
            performance._stat("http_retries")
            await asyncio.sleep(1.25)
            raw_html = await _ORIGINAL_PEISSER_BUNDLE(url)
        performance._put_html_cache(key, raw_html)
        performance._stat("html_network_fetches")
        return raw_html


def peisser_parse_cached(url: str, raw_html: str) -> Any:
    if _ORIGINAL_PEISSER_PARSE is None:
        raise RuntimeError("Peisser-Parser ist noch nicht registriert")
    key = _cache_key("peisser-parse", url, raw_html)
    current = performance._PARSE_CACHE.get(key)
    if current is not None:
        performance._PARSE_CACHE.move_to_end(key)
        performance._stat("parse_cache_hits")
        return copy.deepcopy(current)
    parsed = _ORIGINAL_PEISSER_PARSE(url, raw_html)
    performance._PARSE_CACHE[key] = copy.deepcopy(parsed)
    performance._PARSE_CACHE.move_to_end(key)
    while len(performance._PARSE_CACHE) > performance.PARSE_CACHE_MAX_ITEMS:
        performance._PARSE_CACHE.popitem(last=False)
    performance._stat("parse_runs")
    return parsed


def _facts_only_match(parsed: Any) -> tuple[dict[str, Any] | None, str | None, float, dict[str, Any]]:
    candidates: list[tuple[dict[str, Any], str, float, dict[str, Any]]] = []
    is_peisser = str(getattr(parsed, "source_name", "") or "") == peisser.PEISSER_SOURCE

    for house in list_houses():
        if is_peisser:
            score, reasons = peisser_repair.structured_match_peisser(house, parsed)
            exact_address = "identische bestätigte Adresse" in reasons
            strong_core = all(
                marker in reasons
                for marker in ("gleicher Ort/PLZ", "gleiche Wohnfläche", "gleiche Grundstücksfläche", "gleiche Zimmerzahl")
            )
            corroborating = {
                marker
                for marker in ("gleiches Baujahr", "gleicher HWB", "gleiche Heizungsart", "gleicher Angebotspreis")
                if marker in reasons
            }
            strong_title = any(reason.startswith("sehr ähnlicher Titel") for reason in reasons)
            method = None
            if exact_address and score >= 10.0:
                method = "exact_address"
            elif strong_core and len(corroborating) >= 2 and score >= 8.5:
                method = "structured_facts"
            elif strong_core and corroborating and strong_title and score >= 9.0:
                method = "structured_facts"
            details = {
                "structured_score": score,
                "reasons": reasons,
                "image_matches": 0,
                "corroborating_facts": sorted(corroborating),
                "automatic_merge": bool(method),
                "images_skipped": bool(method),
            }
        else:
            score, reasons = quality.structured_match_conservative(house, parsed)
            exact_address = "identische bestätigte Adresse" in reasons
            strong_core = all(
                marker in reasons
                for marker in ("gleicher Ort/PLZ", "gleiche Wohnfläche", "gleiche Grundstücksfläche", "gleiche Zimmerzahl")
            )
            corroborating = any(
                marker in reasons for marker in ("gleiches Baujahr", "gleicher HWB", "gleiche Heizungsart")
            )
            strong_title = any(reason.startswith("sehr ähnlicher Titel") for reason in reasons)
            method = None
            if exact_address and score >= 10.0:
                method = "exact_address"
            elif strong_core and corroborating and strong_title and score >= 9.0:
                method = "structured_facts"
            details = {
                "structured_score": score,
                "reasons": reasons,
                "image_matches": 0,
                "automatic_merge": bool(method),
                "images_skipped": bool(method),
            }

        if method:
            candidates.append((house, method, float(score), details))

    # Only skip image comparison when the facts identify exactly one house. If several
    # houses qualify, the existing image-assisted algorithm remains the tie-breaker.
    if len(candidates) == 1:
        performance._stat("remote_image_checks_avoided")
        return candidates[0]
    return None, None, 0.0, {"ambiguous_facts_matches": len(candidates)}


async def find_probable_duplicate_resource_aware(
    parsed: Any,
) -> tuple[dict[str, Any] | None, str | None, float, dict[str, Any]]:
    facts_match = _facts_only_match(parsed)
    if facts_match[0] is not None:
        return facts_match
    if _ORIGINAL_FIND_DUPLICATE is None:
        return None, None, 0.0, facts_match[3]
    return await _ORIGINAL_FIND_DUPLICATE(parsed)


async def download_pending_media_optimized(house_id: str, limit: int = 120) -> None:
    if performance._ORIGINAL_MEDIA_DOWNLOAD is None:
        return
    before = {
        str(item.get("id") or ""): dict(item)
        for item in list_media(house_id)
        if str(item.get("download_status") or "") == "pending"
    }
    if not before:
        performance._stat("empty_media_downloads_avoided")
        return

    pending_image_ids = {
        media_id for media_id, item in before.items() if str(item.get("kind") or "image") == "image"
    }
    token = performance._IN_MEDIA_DOWNLOAD.set(True)
    try:
        await performance._ORIGINAL_MEDIA_DOWNLOAD(house_id, limit)
    finally:
        performance._IN_MEDIA_DOWNLOAD.reset(token)

    if not pending_image_ids or performance._ORIGINAL_CLEANUP is None:
        return
    after = {str(item.get("id") or ""): item for item in list_media(house_id)}
    image_changed = any(
        str((after.get(media_id) or {}).get("download_status") or "") in {"downloaded", "skipped"}
        for media_id in pending_image_ids
    )
    if not image_changed:
        performance._stat("empty_media_cleanups_avoided")
        return

    await asyncio.to_thread(performance._ORIGINAL_CLEANUP, house_id)
    performance._RECENT_CLEANUP[house_id] = time.monotonic()
    performance._stat("media_cleanups")


async def spaced_scheduler_loop() -> None:
    await asyncio.sleep(30)
    while True:
        try:
            if search_automation.search_automation_enabled():
                from datetime import datetime, timezone

                current = datetime.now(timezone.utc)
                due = [profile for profile in list_search_profiles() if search_automation.profile_is_due(profile, current)]
                for index, profile in enumerate(due):
                    try:
                        result = await search_automation.execute_profile_cycle(str(profile["id"]))
                        print(f"HausCheck Suche: {result}", flush=True)
                    except Exception as exc:
                        print(f"HausCheck Suche fehlgeschlagen für {profile.get('id')}: {exc}", flush=True)
                    if index + 1 < len(due):
                        # Short cooling/yield interval between profiles; all profiles are still run.
                        await asyncio.sleep(3)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"HausCheck Such-Scheduler Fehler: {exc}", flush=True)
        await asyncio.sleep(search_automation.scheduler_poll_seconds())


def register_search_performance_extra() -> None:
    global _PATCHED
    global _ORIGINAL_PEISSER_BUNDLE, _ORIGINAL_PEISSER_PARSE, _ORIGINAL_FIND_DUPLICATE
    if _PATCHED:
        return

    _ORIGINAL_PEISSER_BUNDLE = peisser._fetch_peisser_bundle
    _ORIGINAL_PEISSER_PARSE = peisser.parse_peisser
    _ORIGINAL_FIND_DUPLICATE = support.find_probable_duplicate

    peisser._fetch_peisser_bundle = peisser_bundle_cached
    peisser.parse_peisser = peisser_parse_cached
    support.find_probable_duplicate = find_probable_duplicate_resource_aware
    quality.find_probable_duplicate_conservative = find_probable_duplicate_resource_aware
    peisser_repair.find_probable_duplicate_peisser = find_probable_duplicate_resource_aware

    performance.download_media_once = download_pending_media_optimized
    main.download_pending_media_files = download_pending_media_optimized
    import_patch.download_pending_media_files = download_pending_media_optimized
    search_automation._search_scheduler_loop = spaced_scheduler_loop
    _PATCHED = True
