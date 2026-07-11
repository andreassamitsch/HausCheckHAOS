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
from fastapi.responses import HTMLResponse, RedirectResponse

from app.analysis_package import analysis_status_html, create_analysis_zip, extract_analysis_json_from_upload, save_analysis
from app.house_manage import delete_house_form_html, edit_house_form_html, expose_upload_html, hero_gallery_html, image_grid_html
from app.main import layout, money, num
from app.storage import get_house, list_evidence, list_media, list_sources
from app.ui_helpers import esc, house_score_html


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


def _methods(route: Any) -> set[str]:
    return set(getattr(route, "methods", set()) or set())


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


def register_house_detail_with_github(app: FastAPI) -> None:
    app.router.routes = [
        route
        for route in app.router.routes
        if not (getattr(route, "path", "") == "/houses/{house_id}" and "GET" in _methods(route))
    ]

    @app.get("/houses/{house_id}", response_class=HTMLResponse)
    def house_detail_github(house_id: str) -> HTMLResponse:
        house = get_house(house_id)
        if not house:
            raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")

        sources = list_sources(house_id)
        media = list_media(house_id)
        evidence = list_evidence(house_id)

        source_rows = "".join(
            f"<tr><td>{esc(src.get('source_name'))}</td><td><a href='{esc(src.get('source_url'))}' target='_blank'>Direktlink</a></td><td>{esc(src.get('parser_status'))}</td></tr>"
            for src in sources
        )
        media_html = image_grid_html(house_id)
        pending_count = len([m for m in media if m.get("download_status") == "pending"])
        failed_count = len([m for m in media if m.get("download_status") == "failed"])
        skipped_count = len([m for m in media if m.get("download_status") == "skipped"])
        downloaded_count = len([m for m in media if m.get("download_status") == "downloaded"])

        evidence_rows = "".join(
            f"<tr><td>{esc(ev.get('field_name'))}</td><td>{esc(ev.get('value_text'))}</td><td>{esc(ev.get('confidence'))}</td><td>{esc(ev.get('source_text_snippet'))}</td></tr>"
            for ev in evidence[:40]
        )
        failed_rows = "".join(
            f"<tr><td>{esc(m.get('kind'))}</td><td>{esc(m.get('original_url'))}</td><td class='danger'>{esc(m.get('download_error'))}</td></tr>"
            for m in media
            if m.get("download_status") == "failed"
        )
        failed_html = f"<h3>Fehlgeschlagene Medien</h3><table><tr><th>Typ</th><th>URL</th><th>Fehler</th></tr>{failed_rows}</table>" if failed_rows else ""
        skipped_rows = "".join(
            f"<tr><td>{esc(m.get('kind'))}</td><td>{esc(m.get('width'))}×{esc(m.get('height'))}</td><td>{esc(m.get('download_error'))}</td></tr>"
            for m in media
            if m.get("download_status") == "skipped"
        )
        skipped_html = f"<h3>Übersprungene Medien</h3><table><tr><th>Typ</th><th>Größe</th><th>Grund</th></tr>{skipped_rows}</table>" if skipped_rows else ""

        body = f"""
        {hero_gallery_html(house_id)}
        <div class="card">
          <h2>{esc(house.get('title'))}</h2>
          <p class="muted">{esc(house.get('location_text') or 'Lage unbekannt')}</p>
          {house_score_html(house)}
          <p>
            <span class="pill">{money(house.get('price_eur'))}</span>
            <span class="pill">{num(house.get('living_area_m2'), ' m² Wfl.')}</span>
            <span class="pill">{num(house.get('plot_area_m2'), ' m² Grund')}</span>
            <span class="pill">HWB {num(house.get('energy_hwb'))}</span>
            <span class="pill">fGEE {num(house.get('energy_fgee'))}</span>
            <span class="pill">Heizung: {esc(house.get('heating') or 'unbekannt')}</span>
          </p>
          <p><span class="pill">Adresse: {esc(house.get('address_status'))}</span><span class="pill">Status: {esc(house.get('status'))}</span></p>
          <p><span class="pill">{downloaded_count} geladen</span><span class="pill">{pending_count} offen</span><span class="pill">{skipped_count} übersprungen</span><span class="pill">{failed_count} Fehler</span></p>
        </div>
        {analysis_status_html(house_id)}
        {github_exchange_card_html(house_id)}
        {edit_house_form_html(house)}
        {expose_upload_html(house_id)}
        <div class="card"><h2>Bilder</h2>{media_html}{failed_html}{skipped_html}</div>
        <div class="card"><h2>Quellen</h2><table><tr><th>Quelle</th><th>Link</th><th>Status</th></tr>{source_rows}</table></div>
        <div class="card"><h2>Feldherkunft</h2><table><tr><th>Feld</th><th>Wert</th><th>Sicherheit</th><th>Snippet</th></tr>{evidence_rows}</table></div>
        {delete_house_form_html(house_id)}
        """
        return layout(str(house.get("title") or "Hausakte"), body)


def register_github_exchange(app: FastAPI) -> None:
    register_house_detail_with_github(app)

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
