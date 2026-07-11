from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import RedirectResponse

from app.analysis_package import create_analysis_zip, extract_analysis_json_from_upload, save_analysis
from app.storage import get_house
from app.ui_helpers import esc


OPTIONS_PATH = Path("/data/options.json")
GITHUB_API = "https://api.github.com"


@dataclass
class GitHubExchangeSettings:
    enabled: bool = False
    repo: str = "andreassamitsch/HausCheckHAOS"
    branch: str = "main"
    token: str = ""
    export_path: str = "ai_exchange/exports/pending"
    result_path: str = "ai_exchange/results/pending"
    done_path: str = "ai_exchange/results/done"
    cleanup_after_import: bool = True

    @property
    def ready(self) -> bool:
        return bool(self.enabled and self.repo and self.token)


def _clean_path(value: str, default: str) -> str:
    text = str(value or default).strip().strip("/")
    text = re.sub(r"/{2,}", "/", text)
    return text or default


def load_settings() -> GitHubExchangeSettings:
    data: dict[str, Any] = {}
    if OPTIONS_PATH.exists():
        try:
            data = json.loads(OPTIONS_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    def env_or_option(name: str, default: Any = "") -> Any:
        env = os.environ.get(f"HAUSCHECK_{name.upper()}")
        if env is not None:
            return env
        return data.get(name, default)

    enabled_raw = env_or_option("github_exchange_enabled", False)
    enabled = enabled_raw is True or str(enabled_raw).strip().lower() in {"1", "true", "yes", "on", "ja"}
    cleanup_raw = env_or_option("github_cleanup_after_import", True)
    cleanup = cleanup_raw is True or str(cleanup_raw).strip().lower() in {"1", "true", "yes", "on", "ja"}

    return GitHubExchangeSettings(
        enabled=enabled,
        repo=str(env_or_option("github_repo", "andreassamitsch/HausCheckHAOS") or "").strip(),
        branch=str(env_or_option("github_branch", "main") or "main").strip(),
        token=str(env_or_option("github_token", "") or "").strip(),
        export_path=_clean_path(str(env_or_option("github_export_path", "ai_exchange/exports/pending") or ""), "ai_exchange/exports/pending"),
        result_path=_clean_path(str(env_or_option("github_result_path", "ai_exchange/results/pending") or ""), "ai_exchange/results/pending"),
        done_path=_clean_path(str(env_or_option("github_done_path", "ai_exchange/results/done") or ""), "ai_exchange/results/done"),
        cleanup_after_import=cleanup,
    )


class GitHubExchangeClient:
    def __init__(self, settings: GitHubExchangeSettings):
        self.settings = settings
        if not settings.ready:
            raise ValueError("GitHub Exchange ist nicht vollständig konfiguriert")
        self.headers = {
            "Authorization": f"Bearer {settings.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "HausCheckHAOS",
        }

    def contents_url(self, path: str) -> str:
        return f"{GITHUB_API}/repos/{self.settings.repo}/contents/{path.strip('/')}"

    async def get_contents(self, path: str) -> Any | None:
        async with httpx.AsyncClient(timeout=60, headers=self.headers, follow_redirects=True) as client:
            response = await client.get(self.contents_url(path), params={"ref": self.settings.branch})
            if response.status_code == 404:
                return None
            if response.status_code >= 400:
                raise HTTPException(status_code=502, detail=f"GitHub Fehler {response.status_code}: {response.text[:300]}")
            return response.json()

    async def put_file(self, path: str, content: bytes, message: str) -> dict[str, Any]:
        existing = await self.get_contents(path)
        payload: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content).decode("ascii"),
            "branch": self.settings.branch,
        }
        if isinstance(existing, dict) and existing.get("sha"):
            payload["sha"] = existing["sha"]
        async with httpx.AsyncClient(timeout=120, headers=self.headers, follow_redirects=True) as client:
            response = await client.put(self.contents_url(path), json=payload)
            if response.status_code >= 400:
                raise HTTPException(status_code=502, detail=f"GitHub Upload Fehler {response.status_code}: {response.text[:500]}")
            return response.json()

    async def read_file_bytes(self, path: str) -> tuple[bytes, str | None]:
        data = await self.get_contents(path)
        if not isinstance(data, dict) or data.get("type") != "file":
            raise FileNotFoundError(path)
        raw = data.get("content") or ""
        content = base64.b64decode(str(raw).replace("\n", ""))
        return content, data.get("sha")

    async def delete_file(self, path: str, message: str) -> bool:
        data = await self.get_contents(path)
        if not isinstance(data, dict) or not data.get("sha"):
            return False
        payload = {"message": message, "sha": data["sha"], "branch": self.settings.branch}
        async with httpx.AsyncClient(timeout=60, headers=self.headers, follow_redirects=True) as client:
            response = await client.delete(self.contents_url(path), json=payload)
            if response.status_code == 404:
                return False
            if response.status_code >= 400:
                raise HTTPException(status_code=502, detail=f"GitHub Delete Fehler {response.status_code}: {response.text[:300]}")
            return True

    async def list_dir(self, path: str) -> list[dict[str, Any]]:
        data = await self.get_contents(path)
        if data is None:
            return []
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]


def exchange_export_filename(house_id: str) -> str:
    return f"{house_id}.zip"


def exchange_export_path(settings: GitHubExchangeSettings, house_id: str) -> str:
    return f"{settings.export_path}/{exchange_export_filename(house_id)}"


def github_exchange_card_html(house_id: str) -> str:
    settings = load_settings()
    if settings.ready:
        status = f"<span class='pill good'>aktiv</span><span class='pill'>{esc(settings.repo)}</span>"
        buttons = f"""
        <form method="post" action="{esc(house_id)}/github-export" data-loading="Analysepaket wird nach GitHub exportiert …" style="display:inline">
          <button type="submit">Analysepaket nach GitHub exportieren</button>
        </form>
        <form method="post" action="{esc(house_id)}/github-import-results" data-loading="GitHub-Ergebnisse werden importiert …" style="display:inline">
          <button class="secondary" type="submit">GitHub-Ergebnisse importieren</button>
        </form>
        """
    else:
        status = "<span class='pill warn'>nicht konfiguriert</span>"
        buttons = "<p class='muted'>In den Add-on-Optionen `github_exchange_enabled`, `github_repo` und `github_token` setzen.</p>"

    return f"""
    <div class="card compact-card">
      <h2>GitHub AI Exchange</h2>
      <p>{status}</p>
      <p class="muted">Export: {esc(settings.export_path)} · Ergebnis: {esc(settings.result_path)}</p>
      {buttons}
    </div>
    """


async def export_house_to_github(house_id: str) -> dict[str, Any]:
    settings = load_settings()
    if not settings.ready:
        raise HTTPException(status_code=400, detail="GitHub Exchange ist nicht vollständig konfiguriert")
    if not get_house(house_id):
        raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")

    zip_path = create_analysis_zip(house_id)
    content = zip_path.read_bytes()
    target_path = exchange_export_path(settings, house_id)
    client = GitHubExchangeClient(settings)
    await client.put_file(target_path, content, f"HausCheck export {house_id}")
    return {"house_id": house_id, "github_path": target_path, "bytes": len(content)}


async def _result_json_paths(client: GitHubExchangeClient, settings: GitHubExchangeSettings) -> list[str]:
    items = await client.list_dir(settings.result_path)
    paths: list[str] = []
    for item in items:
        item_type = item.get("type")
        item_path = str(item.get("path") or "")
        name = str(item.get("name") or "")
        if item_type == "file" and name.endswith(".json"):
            paths.append(item_path)
        elif item_type == "dir":
            candidate = f"{item_path}/hauscheck_analysis.json"
            if await client.get_contents(candidate):
                paths.append(candidate)
    return paths


def _done_json_path(settings: GitHubExchangeSettings, house_id: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{settings.done_path}/{house_id}/hauscheck_analysis_{stamp}.json"


async def _delete_export_zip_for_house(client: GitHubExchangeClient, settings: GitHubExchangeSettings, house_id: str) -> list[str]:
    deleted: list[str] = []
    exact = exchange_export_path(settings, house_id)
    if await client.delete_file(exact, f"HausCheck cleanup export {house_id}"):
        deleted.append(exact)
    # Fallback: ältere oder manuell benannte Dateien mit house_id im Namen entfernen.
    for item in await client.list_dir(settings.export_path):
        path = str(item.get("path") or "")
        name = str(item.get("name") or "")
        if item.get("type") == "file" and house_id in name and name.lower().endswith(".zip") and path not in deleted:
            if await client.delete_file(path, f"HausCheck cleanup export {house_id}"):
                deleted.append(path)
    return deleted


async def import_results_from_github() -> dict[str, Any]:
    settings = load_settings()
    if not settings.ready:
        raise HTTPException(status_code=400, detail="GitHub Exchange ist nicht vollständig konfiguriert")
    client = GitHubExchangeClient(settings)
    result_paths = await _result_json_paths(client, settings)

    imported: list[dict[str, Any]] = []
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
                raise ValueError(f"Hausakte {house_id} nicht gefunden")

            save_analysis(house_id, data)
            imported.append({"house_id": house_id, "path": path})

            if settings.cleanup_after_import:
                done_path = _done_json_path(settings, house_id)
                await client.put_file(done_path, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"), f"HausCheck imported analysis {house_id}")
                if await client.delete_file(path, f"HausCheck remove imported result {house_id}"):
                    cleaned.append(path)
                cleaned.extend(await _delete_export_zip_for_house(client, settings, house_id))
        except Exception as exc:
            errors.append({"path": path, "error": str(exc)[:500]})

    return {"imported": imported, "errors": errors, "cleaned": cleaned, "checked": len(result_paths)}


def register_github_exchange(app: FastAPI) -> None:
    @app.post("/houses/{house_id}/github-export")
    async def github_export_house(house_id: str) -> RedirectResponse:
        await export_house_to_github(house_id)
        return RedirectResponse(f"../{house_id}", status_code=303)

    @app.post("/houses/{house_id}/github-import-results")
    async def github_import_results_for_house(house_id: str) -> RedirectResponse:
        await import_results_from_github()
        return RedirectResponse(f"../{house_id}", status_code=303)

    @app.post("/github/import-results")
    async def github_import_results_global(return_to: str | None = Form(None)) -> RedirectResponse:
        await import_results_from_github()
        return RedirectResponse(return_to or "../", status_code=303)

    @app.get("/github/status")
    async def github_status() -> dict[str, Any]:
        settings = load_settings()
        status: dict[str, Any] = {
            "enabled": settings.enabled,
            "ready": settings.ready,
            "repo": settings.repo,
            "branch": settings.branch,
            "export_path": settings.export_path,
            "result_path": settings.result_path,
            "done_path": settings.done_path,
            "cleanup_after_import": settings.cleanup_after_import,
        }
        if settings.ready:
            client = GitHubExchangeClient(settings)
            status["pending_exports"] = len(await client.list_dir(settings.export_path))
            status["pending_results"] = len(await _result_json_paths(client, settings))
        return status
