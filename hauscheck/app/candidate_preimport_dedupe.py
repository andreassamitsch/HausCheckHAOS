from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from fastapi import FastAPI

import app.github_auto_export as github_auto_export
import app.gmail_exchange as gmail_exchange
import app.immoscout_support as support
import app.main as main
import app.pipeline_status as pipeline_status
import app.search_automation as search_automation
from app.storage import (
    add_evidence,
    connect,
    get_house,
    get_search_profile,
    list_media,
    list_search_candidates,
    list_sources,
    now_iso,
    upsert_search_candidate,
)


_PATCHED = False
_ORIGINAL_RUN_SEARCH: Callable[[str, int], Awaitable[int]] | None = None

HOUSE_FIELDS = (
    "title",
    "location_text",
    "address_status",
    "price_eur",
    "living_area_m2",
    "plot_area_m2",
    "rooms",
    "year_built",
    "heating",
    "energy_hwb",
    "energy_fgee",
    "energy_class_hwb",
    "energy_class_fgee",
)


def _house_snapshot(house: dict[str, Any] | None) -> dict[str, Any]:
    source = house or {}
    return {field: source.get(field) for field in HOUSE_FIELDS}


def _matching_source(house_id: str, parsed: Any) -> dict[str, Any] | None:
    canonical = support.canonical_listing_url(parsed.source_url)
    for source in list_sources(house_id):
        if support.canonical_listing_url(str(source.get("source_url") or "")) == canonical:
            return source
        if (
            parsed.external_id
            and str(source.get("external_id") or "") == str(parsed.external_id)
            and str(source.get("source_name") or "") == str(parsed.source_name)
        ):
            return source
    return None


def _source_signature(source: dict[str, Any] | None) -> tuple[Any, ...] | None:
    if not source:
        return None
    warnings = source.get("parser_warnings")
    try:
        warnings = json.dumps(json.loads(str(warnings or "[]")), ensure_ascii=False, sort_keys=True)
    except Exception:
        warnings = str(warnings or "")
    return (
        str(source.get("source_name") or ""),
        support.canonical_listing_url(str(source.get("source_url") or "")),
        str(source.get("external_id") or ""),
        str(source.get("description") or ""),
        str(source.get("parser_status") or ""),
        warnings,
    )


def _stored_evidence_signature(source_id: str | None) -> set[tuple[str, str, str, str, str]]:
    if not source_id:
        return set()
    with connect() as con:
        rows = con.execute(
            """
            SELECT field_name, value_text, source_label, source_text_snippet, confidence
            FROM field_evidence
            WHERE source_id = ?
            """,
            (source_id,),
        ).fetchall()
    return {
        (
            str(row["field_name"] or ""),
            str(row["value_text"] or ""),
            str(row["source_label"] or ""),
            str(row["source_text_snippet"] or ""),
            str(row["confidence"] or ""),
        )
        for row in rows
    }


def _parsed_evidence_signature(parsed: Any) -> set[tuple[str, str, str, str, str]]:
    result: set[tuple[str, str, str, str, str]] = set()
    for item in parsed.evidence or []:
        result.add(
            (
                str(item.get("field_name") or item.get("field") or "unknown"),
                str(item.get("value")) if item.get("value") is not None else "",
                str(item.get("source_label") or ""),
                str(item.get("source_text_snippet") or ""),
                str(item.get("confidence") or "unknown"),
            )
        )
    return result


def _media_signature(house_id: str) -> set[tuple[str, str, str, str]]:
    return {
        (
            str(item.get("kind") or ""),
            str(item.get("original_url") or ""),
            str(item.get("download_status") or ""),
            str(item.get("content_hash") or ""),
        )
        for item in list_media(house_id)
    }


def update_house_from_source_refresh(house_id: str, parsed: Any, *, same_source: bool) -> dict[str, Any]:
    """Keep the summary stable across brokers while refreshing a sole known source fully."""
    house = get_house(house_id) or {}
    source_count = len(list_sources(house_id))
    sole_source_refresh = same_source and source_count <= 1
    fields: dict[str, Any] = {}

    title = str(parsed.title or "").strip()
    current_title = str(house.get("title") or "").strip()
    if title and (
        not current_title
        or current_title.startswith("ImmobilienScout24 Exposé")
        or sole_source_refresh
    ):
        fields["title"] = title

    if parsed.location_text and (
        not house.get("location_text")
        or (parsed.address_status == "exact" and str(house.get("address_status") or "") != "exact")
        or sole_source_refresh
    ):
        fields["location_text"] = parsed.location_text
        fields["address_status"] = parsed.address_status

    if parsed.price_eur is not None:
        current_price = house.get("price_eur")
        if current_price in (None, "") or sole_source_refresh:
            fields["price_eur"] = parsed.price_eur
        else:
            try:
                fields["price_eur"] = min(int(float(current_price)), int(parsed.price_eur))
            except Exception:
                fields["price_eur"] = parsed.price_eur

    for field, value in {
        "living_area_m2": parsed.living_area_m2,
        "plot_area_m2": parsed.plot_area_m2,
        "rooms": parsed.rooms,
        "year_built": parsed.year_built,
        "heating": parsed.heating,
        "energy_hwb": parsed.energy_hwb,
        "energy_fgee": parsed.energy_fgee,
        "energy_class_hwb": parsed.energy_class_hwb,
        "energy_class_fgee": parsed.energy_class_fgee,
    }.items():
        if value is not None and (house.get(field) in (None, "") or sole_source_refresh):
            fields[field] = value

    fields = {
        key: value
        for key, value in fields.items()
        if str(house.get(key) if house.get(key) is not None else "") != str(value if value is not None else "")
    }
    if not fields:
        return {}

    fields["updated_at"] = now_iso()
    sql = ", ".join(f"{key} = ?" for key in fields)
    with connect() as con:
        con.execute(f"UPDATE houses SET {sql} WHERE id = ?", list(fields.values()) + [house_id])
        con.commit()
    fields.pop("updated_at", None)
    return fields


def _candidate_seen_in_run(before: dict[str, str], candidate: dict[str, Any]) -> bool:
    candidate_id = str(candidate.get("id") or "")
    if candidate_id not in before:
        return True
    return str(candidate.get("last_seen_at") or "") != before[candidate_id]


def _mark_candidate_existing(
    profile_id: str,
    candidate: dict[str, Any],
    parsed: Any,
    house_id: str,
    *,
    changed: bool,
    method: str,
    details: dict[str, Any],
) -> None:
    reason = (
        "Bestehende Hausakte wurde mit neuen Informationen aktualisiert."
        if changed
        else "Inserat gehört zu einer bereits bekannten Hausakte; keine neuen Informationen."
    )
    reasons = [reason, f"Deduplizierung: {method}"]
    if details.get("reasons"):
        reasons.append(" · ".join(str(item) for item in details["reasons"][:4]))

    stored = upsert_search_candidate(
        profile_id,
        parsed.source_url,
        parsed.title or candidate.get("title") or main.title_from_listing_url(parsed.source_url),
        status="imported",
        imported_house_id=house_id,
        facts=main.facts_from_parsed(parsed),
        filter_reasons=reasons,
    )
    candidate_id = str(stored.get("id") or candidate.get("id") or "")
    with connect() as con:
        con.execute(
            """
            UPDATE search_candidates
            SET status = 'imported', imported_house_id = ?, decision = ?, provider = ?,
                external_id = ?, canonical_url = ?, raw_data_json = ?, last_seen_at = ?
            WHERE id = ?
            """,
            (
                house_id,
                "existing_updated" if changed else "existing_known",
                support.provider_for_url(parsed.source_url),
                parsed.external_id,
                support.canonical_listing_url(parsed.source_url),
                json.dumps(
                    {
                        "duplicate_method": method,
                        "duplicate_details": details,
                        "existing_house_id": house_id,
                        "updated": changed,
                    },
                    ensure_ascii=False,
                ),
                now_iso(),
                candidate_id,
            ),
        )
        con.commit()


def _replace_source_evidence(house_id: str, source_id: str, parsed: Any) -> None:
    with connect() as con:
        con.execute("DELETE FROM field_evidence WHERE source_id = ?", (source_id,))
        con.commit()
    add_evidence(house_id, source_id, parsed.evidence or [])


async def _merge_into_existing_house(
    profile_id: str,
    candidate: dict[str, Any],
    parsed: Any,
    raw_html: str,
    house: dict[str, Any],
    method: str,
    score: float,
    details: dict[str, Any],
) -> bool:
    house_id = str(house["id"])
    before_house = _house_snapshot(get_house(house_id))
    before_source = _matching_source(house_id, parsed)
    before_source_signature = _source_signature(before_source)
    before_evidence = _stored_evidence_signature(str(before_source.get("id")) if before_source else None)
    parsed_evidence = _parsed_evidence_signature(parsed)
    before_media = _media_signature(house_id)

    source, same_source = support._store_or_refresh_source(house_id, parsed, raw_html)
    source_id = str(source.get("id") or "")
    updated_fields = update_house_from_source_refresh(house_id, parsed, same_source=same_source)
    _replace_source_evidence(house_id, source_id, parsed)
    support._queue_media(house_id, source_id, parsed)

    queued_media = _media_signature(house_id)
    media_added = queued_media - before_media
    if media_added:
        await main.download_pending_media_files(house_id)
        support.dedupe_house_images_perceptually(house_id)

    after_source = _matching_source(house_id, parsed)
    after_source_signature = _source_signature(after_source)
    after_media = _media_signature(house_id)
    after_house = _house_snapshot(get_house(house_id))

    changed_fields = [field for field in HOUSE_FIELDS if str(before_house.get(field) or "") != str(after_house.get(field) or "")]
    source_changed = before_source is None or before_source_signature != after_source_signature
    evidence_changed = before_evidence != parsed_evidence
    media_changed = before_media != after_media
    changed = bool(source_changed or evidence_changed or media_changed or changed_fields or updated_fields)

    if before_source is None:
        support._record_duplicate(house_id, parsed, method, score, details)

    _mark_candidate_existing(
        profile_id,
        candidate,
        parsed,
        house_id,
        changed=changed,
        method=method,
        details={
            **details,
            "changed_fields": changed_fields,
            "new_source": before_source is None,
            "media_added": len(media_added),
        },
    )

    if changed:
        pipeline_status.set_pipeline_stage(
            house_id,
            "source_merged",
            "ok",
            "Bestehende Hausakte wurde aus einem erneut gefundenen Inserat ergänzt oder aktualisiert.",
        )
        try:
            await github_auto_export.auto_export_house_to_github(house_id)
        except Exception as exc:
            pipeline_status.set_pipeline_stage(
                house_id,
                "error",
                "error",
                "Neue Informationen wurden gespeichert, der KI-Export ist jedoch fehlgeschlagen.",
                error=str(exc),
            )
        try:
            await gmail_exchange.send_analysis_zip_via_gmail(house_id)
        except Exception:
            pass
    return changed


async def run_search_with_preimport_dedupe(profile_id: str, max_results: int = 80) -> int:
    if not _ORIGINAL_RUN_SEARCH:
        return 0
    before = {
        str(item.get("id") or ""): str(item.get("last_seen_at") or "")
        for item in list_search_candidates(profile_id)
    }
    found = await _ORIGINAL_RUN_SEARCH(profile_id, max_results)
    profile = get_search_profile(profile_id)
    if not profile:
        return found

    for candidate in list_search_candidates(profile_id):
        if not _candidate_seen_in_run(before, candidate):
            continue
        source_url = str(candidate.get("source_url") or "")
        if support.provider_for_url(source_url) not in {support.WILLHABEN_SOURCE, support.IMMOSCOUT_SOURCE}:
            continue
        try:
            raw_html = await main.fetch_html(source_url)
            parsed = main.parse_listing(source_url, raw_html)
            existing = support.find_existing_house_for_source(source_url, parsed)
            method = "same_source" if existing else None
            score = 100.0 if existing else 0.0
            details: dict[str, Any] = {"automatic_merge": bool(existing)}
            if not existing:
                existing, method, score, details = await support.find_probable_duplicate(parsed)
            if not existing or not method:
                continue
            await _merge_into_existing_house(
                profile_id,
                candidate,
                parsed,
                raw_html,
                existing,
                method,
                score,
                details,
            )
        except Exception as exc:
            # A failed duplicate check must not hide a genuinely new candidate.
            with connect() as con:
                con.execute(
                    "UPDATE search_candidates SET auto_import_error = ? WHERE id = ?",
                    (f"Deduplizierung fehlgeschlagen: {str(exc)[:700]}", candidate.get("id")),
                )
                con.commit()
    return found


def register_candidate_preimport_dedupe(app: FastAPI) -> None:
    global _PATCHED, _ORIGINAL_RUN_SEARCH
    if _PATCHED:
        return
    _ORIGINAL_RUN_SEARCH = search_automation.run_search_profile
    support._update_house_from_source = update_house_from_source_refresh
    search_automation.run_search_profile = run_search_with_preimport_dedupe
    main.run_search_profile = run_search_with_preimport_dedupe
    _PATCHED = True
