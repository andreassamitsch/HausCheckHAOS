from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException

import app.candidate_preimport_dedupe as candidate_dedupe
import app.github_auto_export as github_auto_export
import app.github_auto_import as github_auto_import
import app.github_exchange as github_exchange
import app.github_import_runtime_fix as import_fix
import app.product_ui as product_ui
from app.analysis_request_guard import (
    force_new_analysis_request,
    load_latest_request,
    mark_latest_request_uploaded,
)
from app.pipeline_status import set_pipeline_stage
from app.storage import connect, get_house, list_media


_PATCHED = False
_ORIGINAL_IMPORT_RESULTS: Callable[[], Awaitable[dict[str, Any]]] | None = None


def _compact(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _stable_url(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))
    except Exception:
        return raw.split("?", 1)[0].split("#", 1)[0]


def source_signature_semantic(source: dict[str, Any] | None) -> tuple[Any, ...] | None:
    if not source:
        return None
    return (
        _compact(source.get("source_name")),
        _stable_url(source.get("source_url")),
        _compact(source.get("external_id")),
        _compact(source.get("description")),
        _compact(source.get("parser_status")),
    )


def stored_evidence_signature_semantic(source_id: str | None) -> set[tuple[str, str, str, str]]:
    if not source_id:
        return set()
    with connect() as con:
        rows = con.execute(
            """
            SELECT field_name, value_text, source_label, confidence
            FROM field_evidence
            WHERE source_id = ?
            """,
            (source_id,),
        ).fetchall()
    return {
        (
            _compact(row["field_name"]),
            _compact(row["value_text"]),
            _compact(row["source_label"]),
            _compact(row["confidence"]),
        )
        for row in rows
    }


def parsed_evidence_signature_semantic(parsed: Any) -> set[tuple[str, str, str, str]]:
    result: set[tuple[str, str, str, str]] = set()
    for item in parsed.evidence or []:
        result.add(
            (
                _compact(item.get("field_name") or item.get("field") or "unknown"),
                _compact(item.get("value")),
                _compact(item.get("source_label")),
                _compact(item.get("confidence") or "unknown"),
            )
        )
    return result


def media_signature_semantic(house_id: str) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for item in list_media(house_id):
        kind = _compact(item.get("kind"))
        content_hash = _compact(item.get("content_hash"))
        identity = content_hash or _stable_url(item.get("original_url"))
        if identity:
            result.add((kind, identity))
    return result


async def manual_retry_export(house_id: str) -> bool:
    return await github_auto_export.auto_export_house_to_github(house_id, force=True)


async def manual_github_export(house_id: str) -> dict[str, Any]:
    settings = github_exchange.load_settings()
    if not settings.ready:
        raise HTTPException(status_code=400, detail="GitHub Exchange ist nicht vollständig konfiguriert")
    if not get_house(house_id):
        raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")

    with force_new_analysis_request():
        zip_path = github_exchange.create_analysis_zip(house_id)
    content = zip_path.read_bytes()
    target_path = github_exchange.exchange_export_path(settings, house_id)
    client = github_exchange.GitHubExchangeClient(settings)
    await client.put_file(target_path, content, f"HausCheck manual export {house_id}")
    mark_latest_request_uploaded(house_id, target_path)
    set_pipeline_stage(
        house_id,
        "waiting_analysis",
        "pending",
        "Analyse wurde manuell neu angestoßen. Das neue ChatGPT-Ergebnis wird erwartet.",
    )
    return {"house_id": house_id, "github_path": target_path, "bytes": len(content), "forced": True}


async def import_results_with_deferred_refresh() -> dict[str, Any]:
    if _ORIGINAL_IMPORT_RESULTS is None:
        return {"imported": [], "errors": [{"error": "Importfunktion nicht registriert"}]}
    result = await _ORIGINAL_IMPORT_RESULTS()
    deferred_exports: list[dict[str, Any]] = []
    for item in result.get("imported") or []:
        house_id = str(item.get("house_id") or "")
        request = load_latest_request(house_id) or {}
        if not request.get("refresh_after_current"):
            continue
        try:
            ok = await github_auto_export.auto_export_house_to_github(house_id)
            deferred_exports.append({"house_id": house_id, "started": bool(ok)})
        except Exception as exc:
            deferred_exports.append({"house_id": house_id, "started": False, "error": str(exc)[:500]})
    result["deferred_exports"] = deferred_exports
    return result


def register_analysis_automation_guard() -> None:
    global _PATCHED, _ORIGINAL_IMPORT_RESULTS
    if _PATCHED:
        return

    candidate_dedupe._source_signature = source_signature_semantic
    candidate_dedupe._stored_evidence_signature = stored_evidence_signature_semantic
    candidate_dedupe._parsed_evidence_signature = parsed_evidence_signature_semantic
    candidate_dedupe._media_signature = media_signature_semantic

    # Der sichtbare Button ist ausdrücklich ein manueller Neustart und darf daher erzwingen.
    product_ui.auto_export_house_to_github = manual_retry_export
    github_exchange.export_house_to_github = manual_github_export

    _ORIGINAL_IMPORT_RESULTS = import_fix.import_results_from_github_fixed
    import_fix.import_results_from_github_fixed = import_results_with_deferred_refresh
    github_exchange.import_results_from_github = import_results_with_deferred_refresh
    github_auto_import.import_results_from_github = import_results_with_deferred_refresh

    _PATCHED = True
