from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import HTTPException

import app.github_auto_import as github_auto_import
import app.github_exchange as github_exchange
from app.analysis_package import extract_analysis_json_from_upload, save_analysis
from app.storage import get_house


_PATCHED = False


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


def _orphan_path(settings: github_exchange.GitHubExchangeSettings, house_id: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    safe_house_id = house_id or "unknown"
    return f"{settings.done_path}/orphaned/{safe_house_id}/hauscheck_analysis_{stamp}.json"


async def import_results_from_github_fixed() -> dict[str, Any]:
    settings = github_exchange.load_settings()
    if not settings.ready:
        raise HTTPException(status_code=400, detail="GitHub Exchange ist nicht vollständig konfiguriert")

    client = github_exchange.GitHubExchangeClient(settings)
    result_paths = await github_exchange._result_json_paths(client, settings)

    imported: list[dict[str, Any]] = []
    orphaned: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    cleaned: list[str] = []

    for path in result_paths:
        try:
            content, _sha = await client.read_file_bytes(path)
            data = extract_analysis_json_from_upload("hauscheck_analysis.json", content)
            house_id = str(data.get("house_id") or "").strip()
            if not house_id:
                raise ValueError("house_id fehlt in hauscheck_analysis.json")

            if not get_house(house_id):
                # Ein Ergebnis für eine gelöschte Hausakte kann nie importiert werden.
                # Es wird erhalten, aber aus pending entfernt, damit es nicht alle fünf
                # Minuten erneut verarbeitet und geloggt wird.
                archive_path = _orphan_path(settings, house_id)
                await client.put_file(
                    archive_path,
                    json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
                    f"HausCheck orphaned analysis {house_id}",
                )
                if await client.delete_file(path, f"HausCheck remove orphaned result {house_id}"):
                    cleaned.append(path)
                cleaned.extend(
                    await github_exchange._delete_export_zip_for_house(client, settings, house_id)
                )
                orphaned.append(
                    {
                        "house_id": house_id,
                        "path": path,
                        "archive_path": archive_path,
                        "reason": "Hausakte nicht mehr vorhanden",
                    }
                )
                continue

            save_analysis(house_id, data)
            imported.append({"house_id": house_id, "path": path})

            if settings.cleanup_after_import:
                done_path = github_exchange._done_json_path(settings, house_id)
                await client.put_file(
                    done_path,
                    json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
                    f"HausCheck imported analysis {house_id}",
                )
                if await client.delete_file(path, f"HausCheck remove imported result {house_id}"):
                    cleaned.append(path)
                cleaned.extend(
                    await github_exchange._delete_export_zip_for_house(client, settings, house_id)
                )
        except Exception as exc:
            errors.append({"path": path, "error": str(exc)[:500]})

    return {
        "imported": imported,
        "orphaned": orphaned,
        "errors": errors,
        "cleaned": cleaned,
        "checked": len(result_paths),
    }


def register_github_import_runtime_fix() -> None:
    global _PATCHED
    if _PATCHED:
        return

    github_exchange.GitHubExchangeClient.delete_file = _delete_file_compatible
    github_exchange.import_results_from_github = import_results_from_github_fixed
    # github_auto_import hat die Funktion beim Modulimport direkt gebunden.
    github_auto_import.import_results_from_github = import_results_from_github_fixed
    _PATCHED = True
