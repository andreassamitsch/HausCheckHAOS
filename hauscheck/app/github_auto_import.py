from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from app.github_exchange import import_results_from_github, load_settings


OPTIONS_PATH = Path("/data/options.json")
_auto_import_task: asyncio.Task | None = None


def _load_options() -> dict[str, Any]:
    if not OPTIONS_PATH.exists():
        return {}
    try:
        return json.loads(OPTIONS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


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


def _option(name: str, default: Any = None) -> Any:
    env = os.environ.get(f"HAUSCHECK_{name.upper()}")
    if env is not None:
        return env
    return _load_options().get(name, default)


def auto_import_enabled() -> bool:
    exchange_enabled = _truthy(_option("github_exchange_enabled", True), True)
    auto_enabled = _truthy(_option("github_auto_import_results", True), True)
    return exchange_enabled and auto_enabled


def auto_import_interval_seconds() -> int:
    raw = _option("github_auto_import_interval_minutes", 5)
    try:
        minutes = int(float(str(raw)))
    except Exception:
        minutes = 5
    minutes = max(1, min(minutes, 1440))
    return minutes * 60


async def _github_auto_import_loop() -> None:
    # kurzer Startversatz, damit Storage/Routes vollständig initialisiert sind
    await asyncio.sleep(20)
    while True:
        sleep_seconds = auto_import_interval_seconds()
        try:
            settings = load_settings()
            if auto_import_enabled() and settings.ready:
                result = await import_results_from_github()
                imported = result.get("imported") or []
                errors = result.get("errors") or []
                checked = result.get("checked") or 0
                if imported or errors:
                    print(
                        f"HausCheck GitHub Auto-Import: geprüft={checked}, importiert={len(imported)}, fehler={len(errors)}",
                        flush=True,
                    )
                    for item in imported[:10]:
                        print(f"HausCheck GitHub Auto-Import OK: {item}", flush=True)
                    for item in errors[:10]:
                        print(f"HausCheck GitHub Auto-Import Fehler: {item}", flush=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"HausCheck GitHub Auto-Import fehlgeschlagen: {exc}", flush=True)
        await asyncio.sleep(sleep_seconds)


def register_github_auto_import(app: FastAPI) -> None:
    @app.on_event("startup")
    async def start_github_auto_import() -> None:
        global _auto_import_task
        if _auto_import_task is None or _auto_import_task.done():
            _auto_import_task = asyncio.create_task(_github_auto_import_loop())
            print("HausCheck GitHub Auto-Import gestartet", flush=True)

    @app.on_event("shutdown")
    async def stop_github_auto_import() -> None:
        global _auto_import_task
        if _auto_import_task and not _auto_import_task.done():
            _auto_import_task.cancel()
        _auto_import_task = None
