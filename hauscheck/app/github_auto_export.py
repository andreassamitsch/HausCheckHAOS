from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.analysis_package import create_analysis_zip
from app.pipeline_status import set_pipeline_stage
from app.storage import get_house


OPTIONS_PATH = Path("/data/options.json")
GITHUB_API = "https://api.github.com"
DEFAULT_REPO = "andreassamitsch/HausCheckAIExchange"


@dataclass
class AutoExportSettings:
    enabled: bool = True
    auto_export_on_import: bool = True
    repo: str = DEFAULT_REPO
    branch: str = "main"
    token: str = ""
    export_path: str = "ai_exchange/exports/pending"

    @property
    def ready(self) -> bool:
        return bool(self.enabled and self.auto_export_on_import and self.repo and self.token)


def _truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if value is True:
        return True
    if value is False:
        return False
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "ja"}:
        return True
    if text in {"0", "false", "no", "off", "nein"}:
        return False
    return default


def _clean_path(value: str, default: str) -> str:
    text = str(value or default).strip().strip("/")
    text = re.sub(r"/{2,}", "/", text)
    return text or default


def _load_options() -> dict[str, Any]:
    if not OPTIONS_PATH.exists():
        return {}
    try:
        return json.loads(OPTIONS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_auto_export_settings() -> AutoExportSettings:
    data = _load_options()

    def env_or_option(name: str, default: Any = "") -> Any:
        env = os.environ.get(f"HAUSCHECK_{name.upper()}")
        if env is not None:
            return env
        return data.get(name, default)

    return AutoExportSettings(
        enabled=_truthy(env_or_option("github_exchange_enabled", True), True),
        auto_export_on_import=_truthy(env_or_option("github_auto_export_on_import", True), True),
        repo=str(env_or_option("github_repo", DEFAULT_REPO) or DEFAULT_REPO).strip(),
        branch=str(env_or_option("github_branch", "main") or "main").strip(),
        token=str(env_or_option("github_token", "") or "").strip(),
        export_path=_clean_path(str(env_or_option("github_export_path", "ai_exchange/exports/pending") or ""), "ai_exchange/exports/pending"),
    )


class GitHubAutoClient:
    def __init__(self, settings: AutoExportSettings):
        self.settings = settings
        self.headers = {
            "Authorization": f"Bearer {settings.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "HausCheckHAOS",
        }

    def contents_url(self, path: str) -> str:
        return f"{GITHUB_API}/repos/{self.settings.repo}/contents/{path.strip('/')}"

    async def get_file(self, path: str) -> dict[str, Any] | None:
        async with httpx.AsyncClient(timeout=60, headers=self.headers, follow_redirects=True) as client:
            response = await client.get(self.contents_url(path), params={"ref": self.settings.branch})
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else None

    async def put_file(self, path: str, content: bytes, message: str) -> None:
        existing = await self.get_file(path)
        payload: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content).decode("ascii"),
            "branch": self.settings.branch,
        }
        if existing and existing.get("sha"):
            payload["sha"] = existing["sha"]
        async with httpx.AsyncClient(timeout=120, headers=self.headers, follow_redirects=True) as client:
            response = await client.put(self.contents_url(path), json=payload)
            response.raise_for_status()


async def auto_export_house_to_github(house_id: str) -> bool:
    """Best-effort Export nach GitHub direkt nach Inserat-Import.

    Fehler blockieren bewusst nicht den eigentlichen Hausimport. Der persistente
    Pipeline-Status macht den aktuellen Stand in der Hausakte sichtbar.
    """
    settings = load_auto_export_settings()
    if not settings.ready:
        set_pipeline_stage(
            house_id,
            "error",
            "error",
            "Automatischer GitHub-Export ist nicht vollständig konfiguriert.",
            error="github_exchange_enabled, github_auto_export_on_import, github_repo oder github_token prüfen",
        )
        return False
    try:
        house = get_house(house_id)
        if not house:
            print(f"HausCheck GitHub Auto-Export übersprungen: Hausakte nicht gefunden: {house_id}", flush=True)
            return False
        set_pipeline_stage(house_id, "exporting", "running", "Analysepaket wird erstellt und nach GitHub übertragen.")
        zip_path = create_analysis_zip(house_id)
        target = f"{settings.export_path}/{house_id}.zip"
        await GitHubAutoClient(settings).put_file(target, zip_path.read_bytes(), f"HausCheck auto export {house_id}")
        set_pipeline_stage(
            house_id,
            "waiting_analysis",
            "pending",
            "Analysepaket wurde bereitgestellt. ChatGPT-Ergebnis wird automatisch erwartet.",
        )
        print(f"HausCheck GitHub Auto-Export OK: {settings.repo}/{target}", flush=True)
        return True
    except Exception as exc:
        set_pipeline_stage(
            house_id,
            "error",
            "error",
            "Analysepaket konnte nicht nach GitHub exportiert werden.",
            error=str(exc),
        )
        print(f"HausCheck GitHub Auto-Export fehlgeschlagen für {house_id}: {exc}", flush=True)
        return False
