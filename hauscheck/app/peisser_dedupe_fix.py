from __future__ import annotations

from typing import Any

from fastapi import FastAPI

import app.candidate_preimport_dedupe as candidate_dedupe
import app.immoscout_support as support
import app.main as main
import app.peisser_support as peisser
from app.storage import list_search_candidates


_PATCHED = False
_ORIGINAL_PEISSER_SEARCH = peisser.run_peisser_search


async def run_peisser_search_with_dedupe(profile_id: str, max_results: int = 80) -> int:
    before = {
        str(item.get("id") or ""): str(item.get("last_seen_at") or "")
        for item in list_search_candidates(profile_id)
    }
    found = await _ORIGINAL_PEISSER_SEARCH(profile_id, max_results)

    for candidate in list_search_candidates(profile_id):
        candidate_id = str(candidate.get("id") or "")
        seen_now = candidate_id not in before or str(candidate.get("last_seen_at") or "") != before[candidate_id]
        if not seen_now or str(candidate.get("status") or "") == "offline":
            continue
        source_url = str(candidate.get("source_url") or "")
        if not peisser.is_peisser_url(source_url):
            continue
        try:
            raw_html = await main.fetch_html(source_url)
            parsed = main.parse_listing(source_url, raw_html)
            if peisser._sold_title(parsed.title):
                peisser._mark_existing_sold({"url": parsed.source_url})
                continue
            existing = support.find_existing_house_for_source(source_url, parsed)
            method = "same_source" if existing else None
            score = 100.0 if existing else 0.0
            details: dict[str, Any] = {"automatic_merge": bool(existing)}
            if not existing:
                existing, method, score, details = await support.find_probable_duplicate(parsed)
            if not existing or not method:
                continue
            await candidate_dedupe._merge_into_existing_house(
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
            from app.storage import connect

            with connect() as con:
                con.execute(
                    "UPDATE search_candidates SET auto_import_error = ? WHERE id = ?",
                    (f"Peisser-Deduplizierung fehlgeschlagen: {str(exc)[:700]}", candidate_id),
                )
                con.commit()
    return found


def register_peisser_dedupe_fix(app: FastAPI) -> None:
    global _PATCHED
    if _PATCHED:
        return
    peisser.run_peisser_search = run_peisser_search_with_dedupe
    _PATCHED = True
