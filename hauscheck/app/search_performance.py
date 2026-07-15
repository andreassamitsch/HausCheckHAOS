from __future__ import annotations

import ast
import asyncio
import copy
import hashlib
import re
import time
from collections import OrderedDict
from contextvars import ContextVar
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

import app.candidate_preimport_dedupe as candidate_dedupe
import app.immoscout_dynamic_search as dynamic
import app.immoscout_search_resilience as resilience
import app.immoscout_support as support
import app.import_patch as import_patch
import app.main as main
import app.media_quality_v2 as media_quality
import app.peisser_support as peisser
import app.search_automation as search_automation
import app.search_lifecycle as lifecycle
import app.search_lifecycle_refresh as lifecycle_refresh
from app.storage import (
    connect,
    get_search_profile,
    list_search_candidates,
    now_iso,
    source_url_exists,
    update_search_profile_run,
    upsert_search_candidate,
)

_PATCHED = False
_HTML_CACHE: OrderedDict[str, tuple[float, str, int]] = OrderedDict()
_PARSE_CACHE: OrderedDict[str, Any] = OrderedDict()
_REMOTE_HASH_CACHE: OrderedDict[str, tuple[float, list[str]]] = OrderedDict()
_IMMOSCOUT_SEARCH_CACHE: OrderedDict[str, tuple[float, tuple[str, str, list[Any], list[dict[str, Any]]]]] = OrderedDict()
_FETCH_LOCKS: dict[str, asyncio.Lock] = {}
_RECENT_CLEANUP: dict[str, float] = {}
_IN_MEDIA_DOWNLOAD: ContextVar[bool] = ContextVar("hauscheck_in_media_download", default=False)
_STATS: dict[str, int] = {}

HTML_CACHE_TTL_SEARCH = 75.0
HTML_CACHE_TTL_DETAIL = 300.0
HTML_CACHE_MAX_ITEMS = 64
HTML_CACHE_MAX_BYTES = 48 * 1024 * 1024
HTML_CACHE_MAX_ENTRY_BYTES = 8 * 1024 * 1024
PARSE_CACHE_MAX_ITEMS = 160
REMOTE_HASH_TTL = 600.0
REMOTE_HASH_MAX_ITEMS = 128
IMMOSCOUT_SEARCH_TTL = 75.0
IMMOSCOUT_SEARCH_MAX_ITEMS = 12
RECENT_CLEANUP_SECONDS = 90.0

_ORIGINAL_FETCH_HTML: Callable[[str], Awaitable[str]] | None = None
_ORIGINAL_PARSE_LISTING: Callable[[str, str], Any] | None = None
_ORIGINAL_REMOTE_HASHES: Callable[[list[str], int], Awaitable[list[str]]] | None = None
_ORIGINAL_MEDIA_DOWNLOAD: Callable[..., Awaitable[None]] | None = None
_ORIGINAL_CLEANUP: Callable[[str], dict[str, Any]] | None = None


def _stat(name: str, amount: int = 1) -> None:
    _STATS[name] = int(_STATS.get(name) or 0) + amount


def _reset_stats() -> None:
    _STATS.clear()


def _area_values(value: object) -> list[str]:
    values: list[object]
    if isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        text = str(value or "").strip()
        values = [text]
        if text.startswith(("[", "(")) and text.endswith(("]", ")")):
            try:
                parsed = ast.literal_eval(text)
                if isinstance(parsed, (list, tuple, set)):
                    values = list(parsed)
            except Exception:
                pass

    result: list[str] = []
    for item in values:
        for area in re.findall(r"(?<![0-9])[1-9][0-9]{3}(?![0-9])", str(item or "")):
            if area not in result:
                result.append(area)
    return result or ["8551"]


def _normalize_portal_url(url: str) -> str:
    raw = str(url or "").strip()
    parts = urlsplit(raw)
    if "willhaben.at" not in parts.netloc.lower():
        return raw

    query: list[tuple[str, str]] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key == "areaId":
            value = _area_values(value)[0]
        query.append((key, value))
    return urlunsplit((parts.scheme or "https", parts.netloc, parts.path, urlencode(query, safe="/"), parts.fragment))


def _repair_profile_areas() -> int:
    changed = 0
    try:
        with connect() as con:
            rows = con.execute("SELECT id, area_ids, search_url FROM search_profiles").fetchall()
            for row in rows:
                areas = ",".join(_area_values(row["area_ids"]))
                raw_urls = str(row["search_url"] or "")
                normalized_urls = "\n".join(
                    _normalize_portal_url(line.strip())
                    for line in raw_urls.splitlines()
                    if line.strip()
                )
                if areas == str(row["area_ids"] or "") and normalized_urls == raw_urls:
                    continue
                con.execute(
                    "UPDATE search_profiles SET area_ids = ?, search_url = ?, updated_at = ? WHERE id = ?",
                    (areas, normalized_urls or raw_urls, now_iso(), row["id"]),
                )
                changed += 1
            con.commit()
    except Exception:
        return 0
    return changed


def _is_search_url(url: str) -> bool:
    lower = str(url or "").lower()
    return any(marker in lower for marker in ("/haus-angebote", "/regional/", "index.php?page="))


def _html_cache_bytes() -> int:
    return sum(entry[2] for entry in _HTML_CACHE.values())


def _put_html_cache(key: str, html: str) -> None:
    size = len(html.encode("utf-8", errors="ignore"))
    if size > HTML_CACHE_MAX_ENTRY_BYTES:
        return
    _HTML_CACHE[key] = (time.monotonic(), html, size)
    _HTML_CACHE.move_to_end(key)
    while len(_HTML_CACHE) > HTML_CACHE_MAX_ITEMS or _html_cache_bytes() > HTML_CACHE_MAX_BYTES:
        _HTML_CACHE.popitem(last=False)


async def fetch_html_cached(url: str) -> str:
    if _ORIGINAL_FETCH_HTML is None:
        raise RuntimeError("HTTP-Abruf ist noch nicht registriert")

    normalized = _normalize_portal_url(url)
    ttl = HTML_CACHE_TTL_SEARCH if _is_search_url(normalized) else HTML_CACHE_TTL_DETAIL
    current = _HTML_CACHE.get(normalized)
    if current and time.monotonic() - current[0] <= ttl:
        _HTML_CACHE.move_to_end(normalized)
        _stat("html_cache_hits")
        return current[1]

    lock = _FETCH_LOCKS.setdefault(normalized, asyncio.Lock())
    async with lock:
        current = _HTML_CACHE.get(normalized)
        if current and time.monotonic() - current[0] <= ttl:
            _HTML_CACHE.move_to_end(normalized)
            _stat("html_cache_hits")
            return current[1]

        try:
            html = await _ORIGINAL_FETCH_HTML(normalized)
        except httpx.HTTPStatusError as exc:
            status = int(exc.response.status_code)
            if status < 500 or status > 599:
                raise
            _stat("http_retries")
            await asyncio.sleep(1.25)
            html = await _ORIGINAL_FETCH_HTML(normalized)
        _stat("html_network_fetches")
        _put_html_cache(normalized, html)
        return html


def parse_listing_cached(url: str, raw_html: str) -> Any:
    if _ORIGINAL_PARSE_LISTING is None:
        raise RuntimeError("Parser ist noch nicht registriert")
    canonical = support.canonical_listing_url(_normalize_portal_url(url))
    digest = hashlib.sha256(raw_html.encode("utf-8", errors="ignore")).hexdigest()
    key = f"{canonical}|{digest}"
    current = _PARSE_CACHE.get(key)
    if current is not None:
        _PARSE_CACHE.move_to_end(key)
        _stat("parse_cache_hits")
        return copy.deepcopy(current)

    parsed = _ORIGINAL_PARSE_LISTING(url, raw_html)
    _PARSE_CACHE[key] = copy.deepcopy(parsed)
    _PARSE_CACHE.move_to_end(key)
    while len(_PARSE_CACHE) > PARSE_CACHE_MAX_ITEMS:
        _PARSE_CACHE.popitem(last=False)
    _stat("parse_runs")
    return parsed


async def remote_image_hashes_cached(urls: list[str], limit: int = 5) -> list[str]:
    if _ORIGINAL_REMOTE_HASHES is None:
        return []
    selected = [str(url) for url in urls[: max(1, int(limit or 5))]]
    key = hashlib.sha256("\n".join(selected).encode("utf-8")).hexdigest()
    current = _REMOTE_HASH_CACHE.get(key)
    if current and time.monotonic() - current[0] <= REMOTE_HASH_TTL:
        _REMOTE_HASH_CACHE.move_to_end(key)
        _stat("image_hash_cache_hits")
        return list(current[1])
    result = await _ORIGINAL_REMOTE_HASHES(selected, limit)
    _REMOTE_HASH_CACHE[key] = (time.monotonic(), list(result))
    _REMOTE_HASH_CACHE.move_to_end(key)
    while len(_REMOTE_HASH_CACHE) > REMOTE_HASH_MAX_ITEMS:
        _REMOTE_HASH_CACHE.popitem(last=False)
    _stat("image_hash_fetches", len(selected))
    return result


async def _immoscout_search_cached(url: str) -> tuple[str, str, list[Any], list[dict[str, Any]]]:
    normalized = _normalize_portal_url(url)
    current = _IMMOSCOUT_SEARCH_CACHE.get(normalized)
    if current and time.monotonic() - current[0] <= IMMOSCOUT_SEARCH_TTL:
        _IMMOSCOUT_SEARCH_CACHE.move_to_end(normalized)
        _stat("search_page_cache_hits")
        raw_html, final_url, candidates, diagnostics = current[1]
        return raw_html, final_url, copy.deepcopy(candidates), copy.deepcopy(diagnostics)
    result = await resilience.fetch_immoscout_search(normalized)
    _IMMOSCOUT_SEARCH_CACHE[normalized] = (time.monotonic(), copy.deepcopy(result))
    _IMMOSCOUT_SEARCH_CACHE.move_to_end(normalized)
    while len(_IMMOSCOUT_SEARCH_CACHE) > IMMOSCOUT_SEARCH_MAX_ITEMS:
        _IMMOSCOUT_SEARCH_CACHE.popitem(last=False)
    _stat("search_page_fetches")
    return result


def _dedupe_guard(house_id: str) -> dict[str, Any]:
    if _ORIGINAL_CLEANUP is None:
        return {"house_id": house_id, "removed": 0, "skipped": True}
    if _IN_MEDIA_DOWNLOAD.get():
        _stat("duplicate_cleanups_avoided")
        return {"house_id": house_id, "removed": 0, "skipped": True, "reason": "download_in_progress"}
    recent = _RECENT_CLEANUP.get(house_id)
    if recent and time.monotonic() - recent <= RECENT_CLEANUP_SECONDS:
        _stat("duplicate_cleanups_avoided")
        return {"house_id": house_id, "removed": 0, "skipped": True, "reason": "already_cleaned"}
    result = _ORIGINAL_CLEANUP(house_id)
    _RECENT_CLEANUP[house_id] = time.monotonic()
    return result


async def download_media_once(house_id: str, limit: int = 120) -> None:
    if _ORIGINAL_MEDIA_DOWNLOAD is None:
        return
    token = _IN_MEDIA_DOWNLOAD.set(True)
    try:
        await _ORIGINAL_MEDIA_DOWNLOAD(house_id, limit)
    finally:
        _IN_MEDIA_DOWNLOAD.reset(token)
    if _ORIGINAL_CLEANUP is not None:
        await asyncio.to_thread(_ORIGINAL_CLEANUP, house_id)
        _RECENT_CLEANUP[house_id] = time.monotonic()
        _stat("media_cleanups")


def _candidate_seen(before: dict[str, dict[str, Any]], candidate: dict[str, Any]) -> bool:
    candidate_id = str(candidate.get("id") or "")
    old = before.get(candidate_id)
    if old is None:
        return True
    return str(candidate.get("last_seen_at") or "") != str(old.get("last_seen_at") or "")


async def _base_portal_search(profile_id: str, max_results: int) -> int:
    profile = get_search_profile(profile_id)
    if not profile:
        raise ValueError("Suchprofil nicht gefunden")

    links: list[str] = []
    seen_keys: set[str] = set()
    diagnostics: list[dict[str, Any]] = []
    explicit_empty_pages = 0
    immoscout_pages = 0

    for raw_search_url in main.resolve_search_urls(profile):
        search_url = _normalize_portal_url(raw_search_url)
        if support.is_immoscout_url(search_url):
            immoscout_pages += 1
            raw_html, final_url, candidates, page_diagnostics = await _immoscout_search_cached(search_url)
            diagnostics.extend({"url": search_url, **item} for item in page_diagnostics)
            if raw_html and resilience._page_flags(raw_html).get("explicit_empty"):
                explicit_empty_pages += 1
            page_links = [candidate.url for candidate in candidates]
        else:
            raw_html = await fetch_html_cached(search_url)
            final_url = search_url
            page_links = main.extract_listing_links(raw_html, final_url)

        for link in page_links:
            key = main.listing_key(link)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            links.append(link)

    limit = max(1, min(int(max_results or 80), 160))
    links = links[:limit]
    if immoscout_pages and not links and explicit_empty_pages < immoscout_pages:
        raise RuntimeError(
            "ImmobilienScout lieferte keine auslesbaren Exposé-Links. "
            + resilience._diagnostic_text(diagnostics)
        )

    for link in links:
        if source_url_exists(link):
            upsert_search_candidate(profile_id, link, main.title_from_listing_url(link), status="imported")
            continue
        try:
            raw_html = await fetch_html_cached(link)
            parsed = parse_listing_cached(link, raw_html)
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


async def run_search_profile_optimized(profile_id: str, max_results: int = 80) -> int:
    started = time.monotonic()
    _reset_stats()
    profile = get_search_profile(profile_id)
    if not profile:
        raise ValueError("Suchprofil nicht gefunden")

    if str(profile.get("source_name") or "") == peisser.PEISSER_SOURCE:
        found = await peisser.run_peisser_search(profile_id, max_results)
        print(
            f"HausCheck Suche optimiert: Profil {profile_id} · Peisser · {found} Treffer · "
            f"{time.monotonic() - started:.1f}s · Cache {_STATS}",
            flush=True,
        )
        return found

    before = {str(item.get("id") or ""): dict(item) for item in list_search_candidates(profile_id)}
    lifecycle_refresh._baseline_existing_candidates(before)
    found = await _base_portal_search(profile_id, max_results)

    # Bekannte Quellen werden genau einmal vollständig aktualisiert.
    await lifecycle_refresh._refresh_seen_imported(profile_id, before)

    merged_houses: set[str] = set()
    for candidate in list_search_candidates(profile_id):
        if not _candidate_seen(before, candidate):
            continue
        source_url = str(candidate.get("source_url") or "")
        if not source_url or source_url_exists(source_url) or str(candidate.get("status") or "") == "imported":
            continue
        if support.provider_for_url(source_url) not in {support.WILLHABEN_SOURCE, support.IMMOSCOUT_SOURCE}:
            continue
        try:
            raw_html = await fetch_html_cached(source_url)
            parsed = parse_listing_cached(source_url, raw_html)
            existing = support.find_existing_house_for_source(source_url, parsed)
            method = "same_source" if existing else None
            score = 100.0 if existing else 0.0
            details: dict[str, Any] = {"automatic_merge": bool(existing)}
            if not existing:
                existing, method, score, details = await support.find_probable_duplicate(parsed)
            if not existing or not method:
                continue
            changed = await candidate_dedupe._merge_into_existing_house(
                profile_id,
                candidate,
                parsed,
                raw_html,
                existing,
                method,
                score,
                details,
            )
            if changed:
                merged_houses.add(str(existing.get("id") or ""))
        except Exception as exc:
            with connect() as con:
                con.execute(
                    "UPDATE search_candidates SET auto_import_error = ? WHERE id = ?",
                    (f"Deduplizierung fehlgeschlagen: {str(exc)[:700]}", candidate.get("id")),
                )
                con.commit()

    try:
        limit = max(1, min(int(max_results or 80), 160))
    except Exception:
        limit = 80
    offline_safe_found = found if found < limit else 0
    lifecycle_result = lifecycle.apply_lifecycle_after_search(profile_id, before, offline_safe_found)
    reanalysis = [
        house_id
        for house_id in lifecycle_result.get("reanalysis_house_ids", [])
        if house_id not in merged_houses
    ]
    if reanalysis:
        await lifecycle_refresh._export_changed_houses(reanalysis)

    elapsed = time.monotonic() - started
    print(
        f"HausCheck Suche optimiert: Profil {profile_id} · {found} Treffer · {elapsed:.1f}s · "
        f"Netz {_STATS.get('html_network_fetches', 0)} · HTML-Cache {_STATS.get('html_cache_hits', 0)} · "
        f"Parser-Cache {_STATS.get('parse_cache_hits', 0)} · Bildbereinigungen {_STATS.get('media_cleanups', 0)} · "
        f"vermiedene Doppelbereinigungen {_STATS.get('duplicate_cleanups_avoided', 0)}",
        flush=True,
    )
    return found


def register_search_performance() -> None:
    global _PATCHED
    global _ORIGINAL_FETCH_HTML, _ORIGINAL_PARSE_LISTING, _ORIGINAL_REMOTE_HASHES
    global _ORIGINAL_MEDIA_DOWNLOAD, _ORIGINAL_CLEANUP
    if _PATCHED:
        return

    _ORIGINAL_FETCH_HTML = main.fetch_html
    _ORIGINAL_PARSE_LISTING = main.parse_listing
    _ORIGINAL_REMOTE_HASHES = support._remote_image_hashes
    _ORIGINAL_MEDIA_DOWNLOAD = media_quality._ORIGINAL_DOWNLOAD or main.download_pending_media_files
    _ORIGINAL_CLEANUP = media_quality.cleanup_house_media

    repaired = _repair_profile_areas()
    main.parse_area_ids = _area_values
    dynamic.parse_search_areas = _area_values

    main.fetch_html = fetch_html_cached
    import_patch.fetch_html = fetch_html_cached
    main.parse_listing = parse_listing_cached
    import_patch.parse_listing = parse_listing_cached
    support._remote_image_hashes = remote_image_hashes_cached

    # Portal-Downloader enthalten historisch eigene Cleanup-Aufrufe. Während des Downloads
    # werden diese unterdrückt; danach läuft genau eine Bereinigung in einem Worker-Thread.
    support.dedupe_house_images_perceptually = _dedupe_guard
    main.download_pending_media_files = download_media_once
    import_patch.download_pending_media_files = download_media_once

    # Finale Suchfunktion ersetzt die gewachsene Wrapper-Kette und wird von manuellen sowie
    # geplanten Läufen über execute_profile_cycle verwendet.
    search_automation.run_search_profile = run_search_profile_optimized
    main.run_search_profile = run_search_profile_optimized

    if repaired:
        print(f"HausCheck Suche: {repaired} fehlerhafte PLZ-/Suchprofilwerte repariert.", flush=True)
    _PATCHED = True
