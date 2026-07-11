from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import RedirectResponse

from app.github_auto_export import auto_export_house_to_github
from app.house_manage import set_house_preview
from app.main import download_pending_media_files, fetch_html, parse_listing
from app.storage import add_evidence, add_media, create_house, create_source, mark_candidates_imported, project_dir


def _methods(route: Any) -> set[str]:
    return set(getattr(route, "methods", set()) or set())


def register_import_patch(app: FastAPI) -> None:
    app.router.routes = [
        route
        for route in app.router.routes
        if not (getattr(route, "path", "") == "/import" and "POST" in _methods(route))
    ]

    @app.post("/import")
    async def import_url_auto_ai(url: str = Form(...), preview_image_url: str | None = Form(None)) -> RedirectResponse:
        if not url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="Ungültige URL")
        raw_html = await fetch_html(url)
        parsed = parse_listing(url, raw_html)

        house = create_house({
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
        })
        set_house_preview(house["id"], preview_image_url)

        hdir = project_dir(house["id"])
        html_path = hdir / "html" / "listing.html"
        html_path.write_text(raw_html, encoding="utf-8")

        source = create_source(house["id"], {
            "source_name": parsed.source_name,
            "source_url": parsed.source_url,
            "external_id": parsed.external_id,
            "description": parsed.description,
            "raw_html_path": str(html_path),
            "parser_status": "success" if not parsed.warnings else "partial",
            "parser_warnings": parsed.warnings,
        })
        add_evidence(house["id"], source["id"], parsed.evidence)
        mark_candidates_imported(parsed.source_url, house["id"])

        for image_url in parsed.image_urls:
            add_media(house["id"], {"source_id": source["id"], "kind": "image", "original_url": image_url, "download_status": "pending"})
        for pdf_url in parsed.pdf_urls:
            add_media(house["id"], {"source_id": source["id"], "kind": "pdf", "original_url": pdf_url, "download_status": "pending"})

        await download_pending_media_files(house["id"])
        await auto_export_house_to_github(str(house["id"]))
        return RedirectResponse(f"houses/{house['id']}", status_code=303)
