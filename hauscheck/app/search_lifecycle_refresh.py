from __future__ import annotations

import json
from typing import Any

import app.main as main
import app.search_automation as search_automation
import app.search_lifecycle as lifecycle
from app.github_auto_export import auto_export_house_to_github
from app.house_manage import update_house_details
from app.storage import (
    add_evidence,
    add_media,
    connect,
    list_search_candidates,
    list_sources,
    project_dir,
    source_url_exists,
    upsert_search_candidate,
)


_patched = False


def _baseline_existing_candidates(before: dict[str, dict[str, Any]]) -> None:
    """Use the values stored before the first 0.9 run as the initial baseline."""
    with connect() as con:
        for candidate_id, candidate in before.items():
            if candidate.get("lifecycle_hash"):
                continue
            snapshot = lifecycle._snapshot(candidate)
            candidate["lifecycle_hash"] = lifecycle._lifecycle_hash(snapshot)
            price = candidate.get("price_eur")
            if price not in (None, ""):
                lifecycle._insert_price_history(con, candidate_id, price, "initial", main.now_iso() if hasattr(main, "now_iso") else lifecycle.now_iso())
        con.commit()


def _material_changes(old: dict[str, Any], parsed: Any) -> list[str]:
    new_data = {
        "title": parsed.title,
        "price_eur": parsed.price_eur,
        "living_area_m2": parsed.living_area_m2,
        "plot_area_m2": parsed.plot_area_m2,
        "energy_hwb": parsed.energy_hwb,
        "preview_image_url": parsed.image_urls[0] if parsed.image_urls else old.get("preview_image_url"),
    }
    return lifecycle._change_descriptions(lifecycle._snapshot(old), new_data)


async def _refresh_imported_candidate(
    profile: dict[str, Any],
    candidate: dict[str, Any],
    old: dict[str, Any],
) -> None:
    source_url = str(candidate.get("source_url") or "")
    if not source_url:
        return
    raw_html = await main.fetch_html(source_url)
    parsed = main.parse_listing(source_url, raw_html)
    _, reasons = main.evaluate_candidate(profile, parsed)
    house_id = str(candidate.get("imported_house_id") or old.get("imported_house_id") or "")

    upsert_search_candidate(
        str(profile["id"]),
        source_url,
        parsed.title or main.title_from_listing_url(source_url),
        status="imported",
        imported_house_id=house_id or None,
        facts=main.facts_from_parsed(parsed),
        filter_reasons=reasons,
    )

    changes = _material_changes(old, parsed)
    if not house_id or not changes:
        return

    house_updates = {
        "title": parsed.title,
        "location_text": parsed.location_text,
        "address_status": parsed.address_status,
        "price_eur": parsed.price_eur,
        "living_area_m2": parsed.living_area_m2,
        "plot_area_m2": parsed.plot_area_m2,
        "rooms": parsed.rooms,
        "year_built": parsed.year_built,
        "heating": parsed.heating,
        "energy_hwb": parsed.energy_hwb,
        "energy_fgee": parsed.energy_fgee,
        "energy_class_hwb": parsed.energy_class_hwb,
        "energy_class_fgee": parsed.energy_class_fgee,
    }
    update_house_details(house_id, {key: value for key, value in house_updates.items() if value not in (None, "")})

    html_path = project_dir(house_id) / "html" / "listing.html"
    html_path.write_text(raw_html, encoding="utf-8")
    sources = list_sources(house_id)
    source = next(
        (
            item
            for item in sources
            if str(item.get("source_url") or "") == source_url
            or (parsed.external_id and str(item.get("external_id") or "") == str(parsed.external_id))
        ),
        sources[0] if sources else None,
    )
    source_id = str(source.get("id")) if source else None
    if source_id:
        with connect() as con:
            con.execute(
                """
                UPDATE listing_sources
                SET description = ?, raw_html_path = ?, parser_status = ?, parser_warnings = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    parsed.description,
                    str(html_path),
                    "success" if not parsed.warnings else "partial",
                    json.dumps(parsed.warnings, ensure_ascii=False),
                    lifecycle.now_iso(),
                    source_id,
                ),
            )
            con.execute("DELETE FROM field_evidence WHERE source_id = ?", (source_id,))
            con.commit()
        add_evidence(house_id, source_id, parsed.evidence)

    for image_url in parsed.image_urls:
        add_media(
            house_id,
            {
                "source_id": source_id,
                "kind": "image",
                "original_url": image_url,
                "download_status": "pending",
            },
        )
    for pdf_url in parsed.pdf_urls:
        add_media(
            house_id,
            {
                "source_id": source_id,
                "kind": "pdf",
                "original_url": pdf_url,
                "download_status": "pending",
            },
        )
    await main.download_pending_media_files(house_id)


async def _refresh_seen_imported(
    profile_id: str,
    before: dict[str, dict[str, Any]],
) -> None:
    profile = main.get_search_profile(profile_id)
    if not profile:
        return
    for candidate in list_search_candidates(profile_id):
        candidate_id = str(candidate.get("id") or "")
        old = before.get(candidate_id)
        if not old:
            continue
        seen_now = str(candidate.get("last_seen_at") or "") != str(old.get("last_seen_at") or "")
        imported = bool(candidate.get("imported_house_id")) or str(candidate.get("status") or "") == "imported" or source_url_exists(str(candidate.get("source_url") or ""))
        if not seen_now or not imported:
            continue
        try:
            await _refresh_imported_candidate(profile, candidate, old)
        except Exception as exc:
            print(f"HausCheck Aktualisierung für {candidate.get('source_url')} fehlgeschlagen: {exc}", flush=True)


async def _export_changed_houses(house_ids: list[str]) -> None:
    for house_id in sorted(set(house_ids))[:5]:
        try:
            await auto_export_house_to_github(house_id)
        except Exception as exc:
            print(f"HausCheck erneute Analyse für {house_id} konnte nicht exportiert werden: {exc}", flush=True)


def register_search_lifecycle_refresh() -> None:
    global _patched
    if _patched:
        return

    async def run_with_refresh(profile_id: str, max_results: int = 80) -> int:
        before = {str(item.get("id")): dict(item) for item in list_search_candidates(profile_id)}
        _baseline_existing_candidates(before)

        # Direkter Basislauf: Die ältere Lifecycle-Hülle wird bewusst umgangen,
        # damit der Vergleich erst nach der Detailaktualisierung erfolgt.
        found = await main.run_search_profile(profile_id, max_results)
        await _refresh_seen_imported(profile_id, before)

        try:
            limit = max(1, min(int(max_results), 160))
        except Exception:
            limit = 80
        # Wenn exakt das Trefferlimit erreicht wurde, kann die Liste abgeschnitten sein.
        # Dann werden ungesehene Altobjekte nicht als offline gewertet.
        offline_safe_found = found if found < limit else 0
        result = lifecycle.apply_lifecycle_after_search(profile_id, before, offline_safe_found)
        if result["changed_ids"] or result["offline_ids"] or result["reactivated_ids"]:
            print(f"HausCheck Inserat-Lifecycle {profile_id}: {result}", flush=True)
        await _export_changed_houses(result["reanalysis_house_ids"])
        return found

    search_automation.run_search_profile = run_with_refresh
    _patched = True
