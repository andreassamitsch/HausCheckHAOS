from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import RedirectResponse
from pypdf import PdfReader

import app.analysis_package as analysis_package
import app.expose_review as expose_review
from app.storage import PROJECTS_DIR, connect, get_house, get_media, list_media


_PATCH_MARKER = "hc-expose-ai-export-v1"
MAX_DIRECT_PDF_BYTES = 35 * 1024 * 1024
MAX_ANALYSIS_PACKAGE_BYTES = 45 * 1024 * 1024
MAX_TEXT_CHARS_PER_PDF = 120_000
MAX_TEXT_CHARS_TOTAL = 250_000

_PATCHED = False
_ORIGINAL_CREATE_ANALYSIS_ZIP = analysis_package.create_analysis_zip
_ORIGINAL_README_PROMPT = analysis_package.readme_prompt


def _methods(route: Any) -> set[str]:
    return set(getattr(route, "methods", set()) or set())


def _find_endpoint(app: FastAPI, path: str, method: str) -> Callable[..., Awaitable[Any]] | None:
    for route in app.router.routes:
        if getattr(route, "path", "") == path and method in _methods(route):
            endpoint = getattr(route, "endpoint", None)
            if callable(endpoint):
                return endpoint
    return None


def _remove_route(app: FastAPI, path: str, method: str) -> None:
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (getattr(route, "path", "") == path and method in _methods(route))
    ]


def _safe_document_name(value: object, fallback: str) -> str:
    name = re.sub(r"[^A-Za-z0-9ÄÖÜäöüß._-]", "_", str(value or fallback).strip())
    return (name or fallback)[:140]


def _local_pdf_items(house_id: str) -> list[tuple[dict[str, Any], Path]]:
    result: list[tuple[dict[str, Any], Path]] = []
    for media in list_media(house_id):
        if (
            media.get("kind") != "pdf"
            or media.get("download_status") != "downloaded"
            or not media.get("local_path")
        ):
            continue
        path = Path(str(media.get("local_path")))
        try:
            path.resolve().relative_to(PROJECTS_DIR.resolve())
        except Exception:
            continue
        if path.exists() and path.is_file():
            result.append((media, path))
    result.sort(key=lambda pair: str(pair[0].get("created_at") or ""))
    return result


def _extract_pdf_text(path: Path) -> tuple[str, int, str | None]:
    try:
        reader = PdfReader(str(path))
        parts: list[str] = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                parts.append("")
        return "\n\n".join(parts).strip(), len(reader.pages), None
    except Exception as exc:
        return "", 0, str(exc)[:300]


def _document_review_state(house_id: str) -> list[dict[str, Any]]:
    try:
        proposals = expose_review.list_address_proposals(house_id)
    except Exception:
        return []
    return [
        {
            "address_text": item.get("address_text"),
            "confidence": item.get("confidence"),
            "status": item.get("status"),
            "created_at": item.get("created_at"),
            "decided_at": item.get("decided_at"),
        }
        for item in proposals
    ]


def enhanced_readme_prompt(house_id: str) -> str:
    base = _ORIGINAL_README_PROMPT(house_id)
    return base + """

## Exposé-Dokumente

Das Paket kann zusätzlich enthalten:

- `documents/*.txt`: aus den Exposé-PDFs extrahierter Text; für Fakten bevorzugt verwenden
- `documents/*.pdf`: Original-Exposé, sofern es innerhalb des sicheren Größenbudgets liegt
- `document_manifest.json`: Dateigrößen, Seitenzahl, Exportmodus und Status von Adressvorschlägen

Bewerte das Objekt nach einem neuen Exposé vollständig neu. Nutze den extrahierten Text für
Eckdaten, Energiekennzahlen, Bauweise, Ausstattung und Sanierungshinweise. Prüfe das Original-PDF
zusätzlich für Pläne, Tabellen und visuelle Zusammenhänge. Eine Adresse darf nur als bestätigt
behandelt werden, wenn sie in `listing.json` als exakte Adresse geführt wird oder im
`document_manifest.json` den Status `accepted` hat. Offene oder verworfene Adressvorschläge
dürfen nicht als gesicherte Objektadresse übernommen werden.

Wenn ein Original-PDF wegen der Größe nicht mitgeliefert wurde, arbeite mit dem extrahierten Text,
den exportierten Bildern und dem Manifest und nenne diese Einschränkung ausdrücklich.
"""


def create_analysis_zip_with_documents(house_id: str) -> Path:
    target = _ORIGINAL_CREATE_ANALYSIS_ZIP(house_id)
    pdfs = _local_pdf_items(house_id)
    manifest: list[dict[str, Any]] = []
    package_bytes = target.stat().st_size if target.exists() else 0
    remaining_text_chars = MAX_TEXT_CHARS_TOTAL

    with zipfile.ZipFile(target, "a", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "documents/README.md",
            (
                "# Exposé-Unterlagen\n\n"
                "Textdateien sind die kompakte Primärquelle. Original-PDFs werden nur aufgenommen, "
                "wenn das gesamte Analysepaket unter dem Sicherheitsbudget bleibt. "
                "Adressvorschläge müssen anhand ihres Status im Manifest behandelt werden.\n"
            ),
        )

        for index, (media, path) in enumerate(pdfs, start=1):
            display_name = str(media.get("display_name") or path.name)
            safe_name = _safe_document_name(display_name, f"expose_{index}.pdf")
            if not safe_name.lower().endswith(".pdf"):
                safe_name += ".pdf"
            stem = Path(safe_name).stem
            text, page_count, extraction_error = _extract_pdf_text(path)
            original_text_chars = len(text)
            allowed_chars = min(MAX_TEXT_CHARS_PER_PDF, remaining_text_chars)
            exported_text = text[:allowed_chars] if allowed_chars > 0 else ""
            text_truncated = len(exported_text) < original_text_chars
            remaining_text_chars = max(0, remaining_text_chars - len(exported_text))

            text_file = f"documents/{index:02d}_{stem}.txt"
            if exported_text:
                zf.writestr(text_file, exported_text)

            pdf_size = path.stat().st_size
            include_original = (
                pdf_size <= MAX_DIRECT_PDF_BYTES
                and package_bytes + pdf_size <= MAX_ANALYSIS_PACKAGE_BYTES
            )
            pdf_file = f"documents/{index:02d}_{safe_name}"
            omitted_reason = None
            if include_original:
                zf.write(path, pdf_file)
                package_bytes += pdf_size
            elif pdf_size > MAX_DIRECT_PDF_BYTES:
                omitted_reason = "Original-PDF überschreitet 35 MB"
            else:
                omitted_reason = "Analysepaket würde das 45-MB-Sicherheitsbudget überschreiten"

            manifest.append(
                {
                    "media_id": media.get("id"),
                    "display_name": display_name,
                    "file_size_bytes": pdf_size,
                    "page_count": page_count,
                    "extraction_status": media.get("extraction_status"),
                    "extraction_summary": media.get("extraction_summary"),
                    "text_file": text_file if exported_text else None,
                    "text_characters_total": original_text_chars,
                    "text_characters_exported": len(exported_text),
                    "text_truncated": text_truncated,
                    "original_pdf_file": pdf_file if include_original else None,
                    "original_pdf_included": include_original,
                    "omitted_reason": omitted_reason,
                    "text_extraction_error": extraction_error,
                    "warning": (
                        "Kein verwertbarer Text und Original-PDF nicht exportiert; Bewertung nur anhand der Bilder möglich."
                        if not exported_text and not include_original
                        else None
                    ),
                }
            )

        zf.writestr(
            "document_manifest.json",
            json.dumps(
                {
                    "limits": {
                        "direct_pdf_max_bytes": MAX_DIRECT_PDF_BYTES,
                        "analysis_package_budget_bytes": MAX_ANALYSIS_PACKAGE_BYTES,
                        "text_chars_per_pdf": MAX_TEXT_CHARS_PER_PDF,
                        "text_chars_total": MAX_TEXT_CHARS_TOTAL,
                    },
                    "documents": manifest,
                    "address_proposals": _document_review_state(house_id),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    return target


def _format_size(value: object) -> str:
    try:
        size = int(value or 0)
    except Exception:
        return "–"
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB".replace(".", ",")
    if size >= 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size} B"


def expose_documents_html_with_delete(house_id: str) -> str:
    expose_review.ensure_expose_review_schema()
    house = get_house(house_id) or {}
    pdfs = [item for item, _ in _local_pdf_items(house_id)]
    pdfs.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    proposals = expose_review.list_address_proposals(house_id)

    document_rows: list[str] = []
    for item in pdfs:
        media_id = str(item.get("id") or "")
        path = Path(str(item.get("local_path") or "Exposé.pdf"))
        name = str(item.get("display_name") or path.name)
        status = str(item.get("extraction_status") or "gespeichert")
        summary = str(item.get("extraction_summary") or "PDF ist gespeichert und kann geöffnet werden.")
        status_class = "bad" if status == "failed" else "good" if status == "success" else ""
        size = int(item.get("file_size_bytes") or 0)
        ai_mode = (
            "KI-Export: Original-PDF und extrahierter Text"
            if size <= MAX_DIRECT_PDF_BYTES
            else "KI-Export: extrahierter Text und Bilder; Original-PDF wegen Größe ausgelassen"
        )
        document_rows.append(
            f"""
            <div class="source-card" style="margin-top:8px">
              <strong>{expose_review.esc(name)}</strong>
              <p class="muted" style="margin:5px 0">{expose_review.esc(_format_size(size))} · {expose_review.esc(expose_review.format_datetime(item.get('created_at')))}</p>
              <p style="margin:5px 0"><span class="pill {status_class}">{expose_review.esc(status)}</span> {expose_review.esc(summary)}</p>
              <p class="muted" style="margin:5px 0">{expose_review.esc(ai_mode)}</p>
              <div class="action-row">
                <a class="button secondary" href="../media/{expose_review.esc(media_id)}" target="_blank">PDF öffnen</a>
                <form method="post" action="{expose_review.esc(house_id)}/expose/{expose_review.esc(media_id)}/reprocess" data-loading="Exposé wird erneut ausgelesen und zur KI-Neubewertung bereitgestellt …">
                  <button class="secondary" type="submit">Erneut auslesen</button>
                </form>
                <form method="post" action="{expose_review.esc(house_id)}/expose/{expose_review.esc(media_id)}/delete" data-loading="PDF wird entfernt und das Analysepaket aktualisiert …" onsubmit="return confirm('Exposé PDF wirklich entfernen? Eine bereits freigegebene Adresse bleibt in der Hausakte bestehen.');">
                  <button class="danger" type="submit">PDF entfernen</button>
                </form>
              </div>
            </div>
            """
        )

    pending_html: list[str] = []
    history_html: list[str] = []
    for proposal in proposals:
        proposal_id = str(proposal.get("id") or "")
        status = str(proposal.get("status") or "pending")
        confidence = str(proposal.get("confidence") or "medium")
        confidence_label = "hoch" if confidence == "high" else "mittel"
        if status == "pending":
            pending_html.append(
                f"""
                <div class="notice warning" style="margin-top:10px">
                  <strong>Adresse im Exposé erkannt – bitte prüfen</strong>
                  <p style="font-size:18px;font-weight:800;margin:8px 0">{expose_review.esc(proposal.get('address_text'))}</p>
                  <p class="muted">Aktuell in der Hausakte: {expose_review.esc(house.get('location_text') or 'keine Adresse')} · Erkennungssicherheit: {expose_review.esc(confidence_label)}</p>
                  <details><summary>Fundstelle im PDF anzeigen</summary><p class="muted">{expose_review.esc(proposal.get('context_text') or 'Keine Textstelle gespeichert.')}</p></details>
                  <div class="action-row" style="margin-top:8px">
                    <form method="post" action="{expose_review.esc(house_id)}/address-proposals/{expose_review.esc(proposal_id)}/accept" data-loading="Adresse wird übernommen und eine neue KI-Bewertung gestartet …"><button type="submit">Adresse übernehmen</button></form>
                    <form method="post" action="{expose_review.esc(house_id)}/address-proposals/{expose_review.esc(proposal_id)}/reject" data-loading="Adressvorschlag wird verworfen und das Analysepaket aktualisiert …"><button class="secondary" type="submit">Verwerfen</button></form>
                  </div>
                </div>
                """
            )
        else:
            label = "übernommen" if status == "accepted" else "verworfen"
            css = "good" if status == "accepted" else ""
            history_html.append(
                f'<span class="pill {css}">{expose_review.esc(proposal.get("address_text"))} · {label}</span>'
            )

    return f"""
    <div class="card compact-card" id="{_PATCH_MARKER}">
      <h2>Exposé und Dokumente</h2>
      <p class="muted">PDFs werden sichtbar gespeichert. Nach Upload, erneutem Auslesen, Adressentscheidung oder Löschen wird automatisch ein neues KI-Analysepaket bereitgestellt.</p>
      {''.join(document_rows) if document_rows else '<p class="muted">Noch kein Exposé PDF gespeichert.</p>'}
      {''.join(pending_html)}
      {f'<details style="margin-top:10px"><summary><strong>Frühere Adressentscheidungen</strong></summary><p>{"".join(history_html)}</p></details>' if history_html else ''}
    </div>
    """


async def _auto_export(house_id: str) -> bool:
    import app.github_auto_export as github_auto_export

    return await github_auto_export.auto_export_house_to_github(house_id)


def _patch_exporters() -> None:
    import app.github_auto_export as github_auto_export
    import app.github_exchange as github_exchange
    import app.gmail_exchange as gmail_exchange

    analysis_package.readme_prompt = enhanced_readme_prompt
    analysis_package.create_analysis_zip = create_analysis_zip_with_documents
    github_auto_export.create_analysis_zip = create_analysis_zip_with_documents
    github_exchange.create_analysis_zip = create_analysis_zip_with_documents
    gmail_exchange.create_analysis_zip = create_analysis_zip_with_documents


def register_expose_ai_export(app: FastAPI) -> None:
    global _PATCHED
    if _PATCHED:
        return

    expose_review.ensure_expose_review_schema()
    _patch_exporters()
    expose_review.expose_documents_html = expose_documents_html_with_delete

    upload_endpoint = _find_endpoint(app, "/houses/{house_id}/expose", "POST")
    reprocess_endpoint = _find_endpoint(app, "/houses/{house_id}/expose/{media_id}/reprocess", "POST")
    accept_endpoint = _find_endpoint(app, "/houses/{house_id}/address-proposals/{proposal_id}/accept", "POST")
    reject_endpoint = _find_endpoint(app, "/houses/{house_id}/address-proposals/{proposal_id}/reject", "POST")

    if upload_endpoint:
        _remove_route(app, "/houses/{house_id}/expose", "POST")

        @app.post("/houses/{house_id}/expose")
        async def upload_expose_and_reanalyse(
            house_id: str,
            file: UploadFile = File(...),
        ) -> RedirectResponse:
            response = await upload_endpoint(house_id=house_id, file=file)
            await _auto_export(house_id)
            return response

    if reprocess_endpoint:
        _remove_route(app, "/houses/{house_id}/expose/{media_id}/reprocess", "POST")

        @app.post("/houses/{house_id}/expose/{media_id}/reprocess")
        async def reprocess_expose_and_reanalyse(house_id: str, media_id: str) -> RedirectResponse:
            response = await reprocess_endpoint(house_id=house_id, media_id=media_id)
            await _auto_export(house_id)
            return response

    if accept_endpoint:
        _remove_route(app, "/houses/{house_id}/address-proposals/{proposal_id}/accept", "POST")

        @app.post("/houses/{house_id}/address-proposals/{proposal_id}/accept")
        async def accept_address_and_reanalyse(house_id: str, proposal_id: str) -> RedirectResponse:
            response = await accept_endpoint(house_id=house_id, proposal_id=proposal_id)
            await _auto_export(house_id)
            return response

    if reject_endpoint:
        _remove_route(app, "/houses/{house_id}/address-proposals/{proposal_id}/reject", "POST")

        @app.post("/houses/{house_id}/address-proposals/{proposal_id}/reject")
        async def reject_address_and_reanalyse(house_id: str, proposal_id: str) -> RedirectResponse:
            response = await reject_endpoint(house_id=house_id, proposal_id=proposal_id)
            await _auto_export(house_id)
            return response

    @app.post("/houses/{house_id}/expose/{media_id}/delete")
    async def delete_expose_and_reanalyse(house_id: str, media_id: str) -> RedirectResponse:
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

        with connect() as con:
            con.execute(
                "UPDATE expose_address_proposals SET media_id = NULL WHERE media_id = ? AND status = 'accepted'",
                (media_id,),
            )
            con.execute(
                "DELETE FROM expose_address_proposals WHERE media_id = ? AND status <> 'accepted'",
                (media_id,),
            )
            con.execute("DELETE FROM media_assets WHERE id = ? AND house_id = ?", (media_id, house_id))
            con.commit()

        try:
            if path.exists():
                path.unlink()
        except Exception:
            pass

        await _auto_export(house_id)
        return RedirectResponse(f"../../../{house_id}", status_code=303)

    _PATCHED = True
