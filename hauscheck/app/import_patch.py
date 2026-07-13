from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import RedirectResponse

from app.github_auto_export import auto_export_house_to_github
from app.gmail_exchange import send_analysis_zip_via_gmail
from app.house_manage import set_house_preview
from app.main import download_pending_media_files, fetch_html, parse_listing
from app.pipeline_status import set_pipeline_stage
from app.storage import (
    add_evidence,
    add_media,
    connect,
    create_house,
    create_source,
    get_house,
    list_media,
    mark_candidates_imported,
    project_dir,
    row_to_dict,
    willhaben_id_from_url,
)


def _methods(route: Any) -> set[str]:
    return set(getattr(route, "methods", set()) or set())


def find_existing_house_for_url(url: str) -> dict[str, Any] | None:
    external_id = willhaben_id_from_url(url)
    with connect() as con:
        row = con.execute(
            """
            SELECT h.*
            FROM houses h
            JOIN listing_sources s ON s.house_id = h.id
            WHERE s.source_url = ?
               OR (? IS NOT NULL AND (s.external_id = ? OR s.source_url LIKE ?))
            ORDER BY h.created_at ASC
            LIMIT 1
            """,
            (url, external_id, external_id, f"%-{external_id}%" if external_id else ""),
        ).fetchone()
    return row_to_dict(row)


async def import_listing_to_pipeline(url: str, preview_image_url: str | None = None) -> dict[str, Any]:
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Ungültige URL")

    existing = find_existing_house_for_url(url)
    if existing:
        mark_candidates_imported(url, str(existing["id"]))
        return {"house": existing, "created": False}

    house_id: str | None = None
    try:
        raw_html = await fetch_html(url)
        parsed = parse_listing(url, raw_html)

        house = create_house(
            {
                "title": parsed.title,
                "location_text": parsed.location_text,
                "address_status": parsed.address_status,
                "price_eur": parsed.price_eur,
                "living_area_m2": parsed.living_area_m2,
                "plot_area_m2": parsed.plot_area_m2,
                "rooms": parsed.rooms,
                "year_built": parsed.year_built,
                "heating": parsed.heating,
                "energy_hwb": parsed.energy_hwb,
                "energy_fgee": parsed.energy_fgee,
                "energy_class_hwb": parsed.energy_class_hwb,
                "energy_class_fgee": parsed.energy_class_fgee,
            }
        )
        house_id = str(house["id"])
        set_pipeline_stage(house_id, "created", "ok", "Hausakte wurde angelegt.")
        set_house_preview(house_id, preview_image_url)

        hdir = project_dir(house_id)
        html_path = hdir / "html" / "listing.html"
        html_path.write_text(raw_html, encoding="utf-8")

        source = create_source(
            house_id,
            {
                "source_name": parsed.source_name,
                "source_url": parsed.source_url,
                "external_id": parsed.external_id,
                "description": parsed.description,
                "raw_html_path": str(html_path),
                "parser_status": "success" if not parsed.warnings else "partial",
                "parser_warnings": parsed.warnings,
            },
        )
        add_evidence(house_id, source["id"], parsed.evidence)
        mark_candidates_imported(parsed.source_url, house_id)
        set_pipeline_stage(house_id, "listing_imported", "ok", "Inseratdaten und Feldherkunft wurden gespeichert.")

        for image_url in parsed.image_urls:
            add_media(
                house_id,
                {
                    "source_id": source["id"],
                    "kind": "image",
                    "original_url": image_url,
                    "download_status": "pending",
                },
            )
        for pdf_url in parsed.pdf_urls:
            add_media(
                house_id,
                {
                    "source_id": source["id"],
                    "kind": "pdf",
                    "original_url": pdf_url,
                    "download_status": "pending",
                },
            )

        set_pipeline_stage(house_id, "media_loading", "running", "Inseratbilder und Dokumente werden geladen.")
        await download_pending_media_files(house_id)
        media = list_media(house_id)
        downloaded = len([item for item in media if item.get("download_status") == "downloaded"])
        failed = len([item for item in media if item.get("download_status") == "failed"])
        set_pipeline_stage(
            house_id,
            "media_ready",
            "ok" if downloaded else "error",
            f"Medienabruf abgeschlossen: {downloaded} geladen, {failed} fehlgeschlagen.",
            error=None if downloaded else "Keine Medien konnten geladen werden.",
        )

        await auto_export_house_to_github(house_id)
        # Gmail bleibt aus Kompatibilitätsgründen im Hintergrund verfügbar, ist standardmäßig deaktiviert.
        await send_analysis_zip_via_gmail(house_id)
        return {"house": get_house(house_id) or house, "created": True}
    except Exception as exc:
        if house_id:
            set_pipeline_stage(
                house_id,
                "error",
                "error",
                "Automatischer Inseratimport ist fehlgeschlagen.",
                error=str(exc),
            )
        raise


def register_import_patch(app: FastAPI) -> None:
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (getattr(route, "path", "") == "/import" and "POST" in _methods(route))
    ]

    @app.post("/import")
    async def import_url_auto_ai(url: str = Form(...), preview_image_url: str | None = Form(None)) -> RedirectResponse:
        result = await import_listing_to_pipeline(url, preview_image_url)
        house = result.get("house") or {}
        return RedirectResponse(f"houses/{house['id']}", status_code=303)
