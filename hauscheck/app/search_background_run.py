from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse

from app.search_automation import execute_profile_cycle, update_profile_automation
from app.storage import get_search_profile, now_iso


_RUNNING: dict[str, asyncio.Task[Any]] = {}


def _methods(route: Any) -> set[str]:
    return set(getattr(route, "methods", set()) or set())


def _remove_route(app: FastAPI, path: str, method: str) -> None:
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (getattr(route, "path", "") == path and method in _methods(route))
    ]


async def _run_profile(profile_id: str) -> None:
    try:
        await execute_profile_cycle(profile_id, force=True)
    except asyncio.CancelledError:
        update_profile_automation(
            profile_id,
            {
                "last_run_status": "abgebrochen",
                "last_error": "Suchlauf wurde beim Beenden des Add-ons abgebrochen.",
                "last_run_at": now_iso(),
            },
        )
        raise
    except Exception as exc:
        # execute_profile_cycle speichert den Fehler ebenfalls; diese Absicherung
        # verhindert zusätzlich eine unobserved-task-Ausnahme im Serverlog.
        update_profile_automation(
            profile_id,
            {
                "last_run_status": "Fehler",
                "last_error": str(exc)[:1000],
                "last_run_at": now_iso(),
            },
        )
    finally:
        _RUNNING.pop(profile_id, None)


def register_search_background_run(app: FastAPI) -> None:
    # Muss als letzter Such-Routen-Patch registriert werden.
    _remove_route(app, "/search/profiles/{profile_id}/run", "POST")

    @app.post("/search/profiles/{profile_id}/run")
    async def start_profile_in_background(profile_id: str) -> RedirectResponse:
        if not get_search_profile(profile_id):
            raise HTTPException(status_code=404, detail="Suchprofil nicht gefunden")

        current = _RUNNING.get(profile_id)
        if current is not None and not current.done():
            update_profile_automation(
                profile_id,
                {
                    "last_run_status": "läuft bereits im Hintergrund",
                    "last_error": None,
                },
            )
            return RedirectResponse(f"../{profile_id}?search_running=1", status_code=303)

        update_profile_automation(
            profile_id,
            {
                "last_run_status": "gestartet · läuft im Hintergrund",
                "last_error": None,
                "last_run_at": now_iso(),
            },
        )
        task = asyncio.create_task(_run_profile(profile_id), name=f"hauscheck-search-{profile_id}")
        _RUNNING[profile_id] = task
        return RedirectResponse(f"../{profile_id}?search_started=1", status_code=303)

    @app.on_event("shutdown")
    async def stop_manual_searches() -> None:
        tasks = [task for task in _RUNNING.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        _RUNNING.clear()
