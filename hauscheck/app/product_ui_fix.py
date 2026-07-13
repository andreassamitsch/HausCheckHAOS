from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse

from app.github_auto_export import auto_export_house_to_github
from app.pipeline_status import set_pipeline_stage
from app.storage import get_house


def _methods(route: Any) -> set[str]:
    return set(getattr(route, "methods", set()) or set())


def register_product_ui_fix(app: FastAPI) -> None:
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", "") == "/houses/{house_id}/analysis/retry"
            and "POST" in _methods(route)
        )
    ]

    @app.post("/houses/{house_id}/analysis/retry")
    async def retry_analysis_fixed(house_id: str) -> RedirectResponse:
        if not get_house(house_id):
            raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")
        set_pipeline_stage(
            house_id,
            "exporting",
            "running",
            "Analysepaket wird erneut erstellt und nach GitHub exportiert.",
        )
        ok = await auto_export_house_to_github(house_id)
        if not ok:
            set_pipeline_stage(
                house_id,
                "error",
                "error",
                "Analyse konnte nicht erneut angestoßen werden.",
            )
        return RedirectResponse(f"/houses/{house_id}", status_code=303)
