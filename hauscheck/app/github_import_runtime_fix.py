from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import HTTPException

import app.analysis_package as analysis_package
import app.github_auto_import as github_auto_import
import app.github_exchange as github_exchange
from app.analysis_request_guard import load_latest_request, register_analysis_request_guard
from app.pipeline_status import set_pipeline_stage
from app.storage import connect, get_house


_PATCHED = False


def _parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text or len(text) == 10:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _pipeline_exported_at(house_id: str) -> datetime | None:
    try:
        with connect() as con:
            row = con.execute(
                "SELECT exported_at FROM house_pipeline_status WHERE house_id = ?",
                (house_id,),
            ).fetchone()
        return _parse_datetime(row[0] if row else None)
    except Exception:
        return None


def _result_matches_latest_request(house_id: str, data: dict[str, Any]) -> tuple[bool, str]:
    latest = load_latest_request(house_id) or {}
    expected_id = str(latest.get("analysis_request_id") or "").strip()
    result_id = str(data.get("analysis_request_id") or "").strip()
    expected_at = _parse_datetime(latest.get("created_at")) or _pipeline_exported_at(house_id)
    generated_at = _parse_datetime(data.get("analysis_date"))

    if expected_id and result_id:
        if result_id == expected_id:
            return True, "Auftragskennung stimmt überein"
        return False, f"Auftragskennung gehört zu einem anderen Export ({result_id[:12]} statt {expected_id[:12]})"

    # Übergangsregel für Ergebnisse aus Paketen vor Einführung der Auftrags-ID:
    # Nur ein tatsächlich nach dem jüngsten Export erzeugtes Ergebnis darf akzeptiert werden.
    if expected_at is not None:
        if generated_at is None:
            return False, "Analysezeitpunkt fehlt; Zuordnung zum jüngsten Export ist nicht möglich"
        if generated_at < expected_at - timedelta(minutes=5):
            return False, "Analyse wurde vor dem jüngsten Export erzeugt"

    if expected_id and not result_id:
        # Ein frisches Legacy-Ergebnis darf einmalig übernommen werden und erhält lokal die
        # bekannte Kennung. Künftige Pakete verlangen die Kennung ausdrücklich im Schema.
        data["analysis_request_id"] = expected_id
        return True, "Frisches Legacy-Ergebnis anhand des Analysezeitpunkts zugeordnet"

    return True, "Kein neuerer Exportkonflikt erkannt"


async def _delete_file_compatible(
    self: github_exchange.GitHubExchangeClient,
    path: str,
    message: str,
) -> bool:
    """GitHub DELETE mit Body, kompatibel mit der installierten httpx-Version."""
    data = await self.get_contents(path)
    if not isinstance(data, dict) or not data.get("sha"):
        return False
    payload = {
        "message": message,
        "sha": data["sha"],
        "branch": self.settings.branch,
    }
    async with httpx.AsyncClient(
        timeout=60,
        headers=self.headers,
        follow_redirects=True,
    ) as client:
        response = await client.request(
            "DELETE",
            self.contents_url(path),
            json=payload,
        )
        if response.status_code == 404:
            return False
        if response.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail=f"GitHub Delete Fehler {response.status_code}: {response.text[:300]}",
            )
        return True


def _archive_path(
    settings: github_exchange.GitHubExchangeSettings,
    category: str,
    house_id: str,
) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    safe_house_id = house_id or "unknown"
    return f"{settings.done_path}/{category}/{safe_house_id}/hauscheck_analysis_{stamp}.json"


async def _archive_result(
    client: github_exchange.GitHubExchangeClient,
    settings: github_exchange.GitHubExchangeSettings,
    category: str,
    house_id: str,
    data: dict[str, Any],
    source_path: str,
    reason: str,
) -> tuple[str, bool]:
    archived = dict(data)
    archived["hauscheck_archive"] = {
        "category": category,
        "reason": reason,
        "source_path": source_path,
        "archived_at": datetime.now(timezone.utc).isoformat(),
    }
    archive_path = _archive_path(settings, category, house_id)
    await client.put_file(
        archive_path,
        json.dumps(archived, ensure_ascii=False, indent=2).encode("utf-8"),
        f"HausCheck archive {category} analysis {house_id}",
    )
    removed = await client.delete_file(source_path, f"HausCheck remove {category} result {house_id}")
    return archive_path, removed


async def import_results_from_github_fixed() -> dict[str, Any]:
    settings = github_exchange.load_settings()
    if not settings.ready:
        raise HTTPException(status_code=400, detail="GitHub Exchange ist nicht vollständig konfiguriert")

    client = github_exchange.GitHubExchangeClient(settings)
    result_paths = await github_exchange._result_json_paths(client, settings)

    imported: list[dict[str, Any]] = []
    orphaned: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    cleaned: list[str] = []

    for path in result_paths:
        try:
            content, _sha = await client.read_file_bytes(path)
            data = analysis_package.extract_analysis_json_from_upload("hauscheck_analysis.json", content)
            house_id = str(data.get("house_id") or "").strip()
            if not house_id:
                raise ValueError("house_id fehlt in hauscheck_analysis.json")

            if not get_house(house_id):
                archive_path, removed = await _archive_result(
                    client,
                    settings,
                    "orphaned",
                    house_id,
                    data,
                    path,
                    "Hausakte nicht mehr vorhanden",
                )
                if removed:
                    cleaned.append(path)
                cleaned.extend(await github_exchange._delete_export_zip_for_house(client, settings, house_id))
                orphaned.append(
                    {
                        "house_id": house_id,
                        "path": path,
                        "archive_path": archive_path,
                        "reason": "Hausakte nicht mehr vorhanden",
                    }
                )
                continue

            matches, match_reason = _result_matches_latest_request(house_id, data)
            if not matches:
                archive_path, removed = await _archive_result(
                    client,
                    settings,
                    "stale",
                    house_id,
                    data,
                    path,
                    match_reason,
                )
                if removed:
                    cleaned.append(path)
                # Das aktuelle Export-ZIP bleibt ausdrücklich bestehen. Nur das alte
                # Ergebnis wird aus pending entfernt.
                set_pipeline_stage(
                    house_id,
                    "waiting_analysis",
                    "pending",
                    f"Veraltetes KI-Ergebnis verworfen: {match_reason}. Neues Ergebnis wird weiter erwartet.",
                )
                stale.append(
                    {
                        "house_id": house_id,
                        "path": path,
                        "archive_path": archive_path,
                        "reason": match_reason,
                    }
                )
                continue

            analysis_package.save_analysis(house_id, data)
            imported.append({"house_id": house_id, "path": path, "match": match_reason})

            if settings.cleanup_after_import:
                done_path = github_exchange._done_json_path(settings, house_id)
                await client.put_file(
                    done_path,
                    json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
                    f"HausCheck imported analysis {house_id}",
                )
                if await client.delete_file(path, f"HausCheck remove imported result {house_id}"):
                    cleaned.append(path)
                cleaned.extend(await github_exchange._delete_export_zip_for_house(client, settings, house_id))
        except Exception as exc:
            errors.append({"path": path, "error": str(exc)[:500]})

    return {
        "imported": imported,
        "orphaned": orphaned,
        "stale": stale,
        "errors": errors,
        "cleaned": cleaned,
        "checked": len(result_paths),
    }


def register_github_import_runtime_fix() -> None:
    global _PATCHED
    if _PATCHED:
        return

    # Muss nach Medien-/PDF-Exportpatches laufen, damit die Auftragskennung den finalen
    # Paketinhalt umschließt und von allen Exportwegen verwendet wird.
    register_analysis_request_guard()
    github_exchange.GitHubExchangeClient.delete_file = _delete_file_compatible
    github_exchange.import_results_from_github = import_results_from_github_fixed
    # github_auto_import hat die Funktion beim Modulimport direkt gebunden.
    github_auto_import.import_results_from_github = import_results_from_github_fixed
    _PATCHED = True
