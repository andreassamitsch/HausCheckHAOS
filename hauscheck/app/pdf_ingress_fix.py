from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

import app.expose_ai_export as expose_ai_export
import app.expose_review as expose_review
from app.storage import PROJECTS_DIR, get_media


_PATCH_MARKER = "hc-pdf-ingress-fix-v1"
_PATCHED = False


def _pdf_media(house_id: str, media_id: str) -> tuple[dict[str, Any], Path]:
    media = get_media(media_id)
    if (
        not media
        or str(media.get("house_id") or "") != house_id
        or media.get("kind") != "pdf"
        or not media.get("local_path")
    ):
        raise HTTPException(status_code=404, detail="Exposé PDF nicht gefunden")

    path = Path(str(media.get("local_path")))
    try:
        path.resolve().relative_to(PROJECTS_DIR.resolve())
    except Exception as exc:
        raise HTTPException(status_code=403, detail="Ungültiger Dokumentpfad") from exc
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="PDF-Datei nicht gefunden")
    return media, path


def _safe_download_name(media: dict[str, Any], path: Path) -> str:
    name = str(media.get("display_name") or path.name or "expose.pdf").strip()
    name = re.sub(r"[\r\n\t]+", " ", name)
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name[:180]


def _patch_document_html() -> None:
    current: Callable[[str], str] = expose_ai_export.expose_documents_html_with_delete
    if getattr(current, "_pdf_ingress_fixed", False):
        return

    def ingress_safe_documents(house_id: str) -> str:
        html = current(house_id)
        # target=_blank öffnet auf Android häufig einen externen Browser ohne
        # Home-Assistant-Ingress-Sitzung und führt deshalb zu "Unauthorized".
        html = re.sub(
            r'(<a class="button secondary" href="\.\./media/([^\"]+)")\s+target="_blank"(>PDF öffnen</a>)',
            r'\1 data-ingress-document="true"\3',
            html,
        )
        html = re.sub(
            r'(<a class="button secondary" href="\.\./media/([^\"]+)" data-ingress-document="true">PDF öffnen</a>)',
            lambda match: (
                match.group(1)
                + f'<a class="button secondary" href="{expose_review.esc(house_id)}/expose/'
                + expose_review.esc(match.group(2))
                + '/download">PDF herunterladen</a>'
            ),
            html,
        )
        return html.replace(
            f'id="{expose_ai_export._PATCH_MARKER}"',
            f'id="{expose_ai_export._PATCH_MARKER}" data-pdf-ingress-fix="{_PATCH_MARKER}"',
            1,
        )

    setattr(ingress_safe_documents, "_pdf_ingress_fixed", True)
    expose_ai_export.expose_documents_html_with_delete = ingress_safe_documents
    expose_review.expose_documents_html = ingress_safe_documents


def register_pdf_ingress_fix(app: FastAPI) -> None:
    global _PATCHED
    if _PATCHED:
        return

    _patch_document_html()

    @app.get("/houses/{house_id}/expose/{media_id}/download")
    async def download_expose_pdf(house_id: str, media_id: str) -> FileResponse:
        media, path = _pdf_media(house_id, media_id)
        return FileResponse(
            path,
            media_type="application/pdf",
            filename=_safe_download_name(media, path),
            content_disposition_type="attachment",
        )

    _PATCHED = True
