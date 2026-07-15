from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse

import app.media_quality_v2 as media_quality
import app.modern_ui as modern_ui
from app.pipeline_status import set_pipeline_stage
from app.storage import get_house


_PATCHED = False
_ORIGINAL_GALLERY_HTML: Callable[[str], str] | None = None


def _methods(route: Any) -> set[str]:
    return set(getattr(route, "methods", set()) or set())


def _remove_route(app: FastAPI, path: str, method: str) -> None:
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (getattr(route, "path", "") == path and method in _methods(route))
    ]


def gallery_with_cleanup_action(house_id: str) -> str:
    gallery = _ORIGINAL_GALLERY_HTML(house_id) if _ORIGINAL_GALLERY_HTML else ""
    hid = modern_ui.esc(house_id)
    return f"""
    <div class="action-row" style="margin:0 0 10px">
      <form method="post" action="{hid}/media/cleanup" data-loading="Bilder werden portalübergreifend verglichen und bereinigt …">
        <button class="secondary" type="submit">Doppelte Bilder bereinigen</button>
      </form>
      <span class="muted">Entfernt gleiche Fotos sowie redundante Raumansichten anderer Inseratanbieter.</span>
    </div>
    {gallery}
    """


def register_media_cleanup_ui(app: FastAPI) -> None:
    global _PATCHED, _ORIGINAL_GALLERY_HTML
    if _PATCHED:
        return

    _ORIGINAL_GALLERY_HTML = modern_ui._gallery_html
    modern_ui._gallery_html = gallery_with_cleanup_action

    _remove_route(app, "/houses/{house_id}/media/cleanup", "POST")

    @app.post("/houses/{house_id}/media/cleanup")
    async def cleanup_house_media_route(house_id: str) -> RedirectResponse:
        if not get_house(house_id):
            raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")
        result = media_quality.cleanup_house_media(house_id)
        removed = int(result.get("removed") or 0)
        remaining = int(result.get("after") or 0)
        message = (
            f"Bildbereinigung abgeschlossen: {removed} überflüssige Bilder entfernt, "
            f"{remaining} eindeutige Bilder verbleiben."
        )
        set_pipeline_stage(house_id, "media_ready", "ok", message)
        return RedirectResponse(
            f"../../../houses/{house_id}?media_cleanup_removed={removed}",
            status_code=303,
        )

    _PATCHED = True
