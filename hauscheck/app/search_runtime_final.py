from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

import app.immoscout_quality as quality
import app.immoscout_support as support
import app.main as main
import app.peisser_runtime_repair as peisser_repair
import app.peisser_support as peisser
import app.search_automation as search_automation
import app.search_lifecycle as lifecycle
import app.search_lifecycle_refresh as lifecycle_refresh
import app.search_performance as performance
import app.search_performance_extra as performance_extra
from app.storage import get_search_profile, list_houses, list_search_candidates

_PATCHED = False
_ORIGINAL_RESOURCE_AWARE: Callable[
    [Any], Awaitable[tuple[dict[str, Any] | None, str | None, float, dict[str, Any]]]
] | None = None


async def duplicate_guard_with_empty_index(
    parsed: Any,
) -> tuple[dict[str, Any] | None, str | None, float, dict[str, Any]]:
    # With no existing house there is nothing to compare against. The historical
    # implementation still downloaded and hashed up to five remote images.
    if not list_houses():
        performance._stat("remote_image_checks_avoided")
        return None, None, 0.0, {"reason": "no_existing_houses", "image_matches": 0}
    if _ORIGINAL_RESOURCE_AWARE is None:
        return None, None, 0.0, {}
    return await _ORIGINAL_RESOURCE_AWARE(parsed)


async def run_search_profile_final(profile_id: str, max_results: int = 80) -> int:
    profile = get_search_profile(profile_id)
    if not profile or str(profile.get("source_name") or "") != peisser.PEISSER_SOURCE:
        return await performance.run_search_profile_optimized(profile_id, max_results)

    started = time.monotonic()
    performance._reset_stats()
    before = {str(item.get("id") or ""): dict(item) for item in list_search_candidates(profile_id)}
    lifecycle_refresh._baseline_existing_candidates(before)

    # Peisser keeps its specialized overview prefilter, page-signature stop and
    # VERKAUFT handling. Detail bundles and parsing are cached by the performance layer.
    found = await peisser.run_peisser_search(profile_id, max_results)
    try:
        limit = max(1, min(int(max_results or 80), 160))
    except Exception:
        limit = 80
    lifecycle_result = lifecycle.apply_lifecycle_after_search(
        profile_id,
        before,
        found if found < limit else 0,
    )
    if lifecycle_result["changed_ids"] or lifecycle_result["offline_ids"] or lifecycle_result["reactivated_ids"]:
        print(f"HausCheck Inserat-Lifecycle {profile_id}: {lifecycle_result}", flush=True)

    print(
        f"HausCheck Suche optimiert: Profil {profile_id} · Peisser · {found} Treffer · "
        f"{time.monotonic() - started:.1f}s · Netz {performance._STATS.get('html_network_fetches', 0)} · "
        f"Cache {performance._STATS.get('peisser_bundle_cache_hits', 0)} · "
        f"Parser-Cache {performance._STATS.get('parse_cache_hits', 0)} · "
        f"Bildprüfungen vermieden {performance._STATS.get('remote_image_checks_avoided', 0)}",
        flush=True,
    )
    return found


def register_search_runtime_final() -> None:
    global _PATCHED, _ORIGINAL_RESOURCE_AWARE
    if _PATCHED:
        return

    _ORIGINAL_RESOURCE_AWARE = performance_extra.find_probable_duplicate_resource_aware
    support.find_probable_duplicate = duplicate_guard_with_empty_index
    quality.find_probable_duplicate_conservative = duplicate_guard_with_empty_index
    peisser_repair.find_probable_duplicate_peisser = duplicate_guard_with_empty_index

    # This is the single final runner used by manual and scheduled profile cycles.
    search_automation.run_search_profile = run_search_profile_final
    main.run_search_profile = run_search_profile_final
    _PATCHED = True
