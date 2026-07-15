from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI

import app.media_quality_v2 as media_quality
from app.storage import list_houses


_PATCHED = False
_BACKGROUND_TASK: asyncio.Task[None] | None = None


def _deferred_startup_summary() -> dict[str, Any]:
    """Keep module registration fast; the real cleanup starts after Uvicorn is ready."""
    return {
        "houses": 0,
        "removed": 0,
        "errors": [],
        "deferred": True,
    }


async def _cleanup_existing_houses_in_background() -> None:
    # Give Home Assistant enough time to complete the ingress health check first.
    await asyncio.sleep(20)
    houses = list_houses()
    checked = 0
    removed = 0
    errors: list[dict[str, str]] = []

    print(
        f"HausCheck Medienbereinigung im Hintergrund gestartet: {len(houses)} Hausakten.",
        flush=True,
    )
    for house in houses:
        house_id = str(house.get("id") or "")
        if not house_id:
            continue
        try:
            result = await asyncio.to_thread(media_quality.cleanup_house_media, house_id)
            checked += 1
            removed += int(result.get("removed") or 0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            errors.append({"house_id": house_id, "error": str(exc)[:300]})
        # Prevent a large existing gallery from monopolising the add-on process.
        await asyncio.sleep(0.35)

    print(
        "HausCheck Medienbereinigung im Hintergrund abgeschlossen: "
        f"{checked} Hausakten geprüft, {removed} Bilder entfernt, {len(errors)} Fehler.",
        flush=True,
    )


async def _schedule_background_cleanup() -> None:
    global _BACKGROUND_TASK
    if _BACKGROUND_TASK is None or _BACKGROUND_TASK.done():
        _BACKGROUND_TASK = asyncio.create_task(
            _cleanup_existing_houses_in_background(),
            name="hauscheck-media-cleanup",
        )


def register_media_startup_fix(app: FastAPI) -> None:
    global _PATCHED
    if _PATCHED:
        return

    # register_media_quality_v2() calls this function synchronously during import.
    # Replacing it here prevents large existing galleries from blocking Uvicorn startup.
    media_quality.cleanup_all_houses = _deferred_startup_summary
    app.add_event_handler("startup", _schedule_background_cleanup)
    _PATCHED = True
