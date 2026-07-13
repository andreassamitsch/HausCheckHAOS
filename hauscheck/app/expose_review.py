from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import RedirectResponse
from pypdf import PdfReader

import app.house_manage as house_manage
import app.product_ui as product_ui
from app.storage import (
    add_evidence,
    add_media,
    connect,
    ensure_columns,
    get_house,
    get_media,
    list_media,
    now_iso,
    project_dir,
    row_to_dict,
)
from app.ui_helpers import esc, format_datetime


_PATCH_MARKER = "hc-expose-review-v1"
_BLOCKED_CONTEXT = re.compile(
    r"\b(?:makler|anbieter|kontakt|impressum|büro|office|kanzlei|immobilien|"
    r"gmbh|kg|e\.u\.|telefon|telefonnummer|e-?mail|homepage|www\.)\b",
    re.IGNORECASE,
)
_POSITIVE_CONTEXT = re.compile(
    r"\b(?:objektadresse|liegenschaftsadresse|adresse\s+der\s+liegenschaft|"
    r"adresse\s+des\s+objekts|objektstandort|standort\s+des\s+objekts)\b",
    re.IGNORECASE,
)
_CITY_STOP = re.compile(
    r"\b(?:Kontakt|Makler|Anbieter|Impressum|Telefon|E-?Mail|Email|Homepage|"
    r"Objekt(?:nummer|daten)?|Preis|Kaufpreis|Wohnfläche|Grundstück|Energie|HWB|"
    r"fGEE|Baujahr|Zimmer|Beschreibung)\b"
)

_STREET_SUFFIX = (
    r"(?i:straße|strasse|gasse|weg|platz|allee|ring|siedlung|zeile|"
    r"gürtel|kai|graben|dorf|berg)"
)
_STREET = (
    rf"(?:(?:[A-ZÄÖÜ][A-Za-zÄÖÜäöüß.'\-]*\s+){{0,4}}"
    rf"[A-ZÄÖÜ][A-Za-zÄÖÜäöüß.'\-]*{_STREET_SUFFIX}|"
    r"(?:Am|An\s+der|Auf\s+der|Im|In\s+der|Unter|Obere|Untere)\s+"
    r"[A-ZÄÖÜ][A-Za-zÄÖÜäöüß.'\-]+(?:\s+[A-Za-zÄÖÜäöüß.'\-]+){0,4})"
)
_CITY_STOP_WORD = (
    r"(?i:Kontakt|Makler|Anbieter|Impressum|Telefon|E-?Mail|Email|Homepage|"
    r"Objekt(?:nummer|daten)?|Preis|Kaufpreis|Wohnfläche|Grundstück|Energie|HWB|"
    r"fGEE|Baujahr|Zimmer|Beschreibung)"
)
_CITY_FIRST = rf"(?!(?:{_CITY_STOP_WORD})\b)[A-ZÄÖÜ][A-Za-zÄÖÜäöüß.'\-]+"
_CITY_NEXT = (
    rf"(?!(?:{_CITY_STOP_WORD})\b)"
    r"(?:[A-ZÄÖÜ][A-Za-zÄÖÜäöüß.'\-]+|am|im|an|der|bei|ob|unter)"
)
_CITY = rf"{_CITY_FIRST}(?:\s+{_CITY_NEXT}){{0,5}}"
_ADDRESS_PATTERNS = [
    re.compile(
        rf"\b(?P<street>{_STREET})\s+(?P<number>\d+[A-Za-z]?(?:/\d+[A-Za-z]?)?)"
        rf"\s*,?\s*(?P<zip>[1-9][0-9]{{3}})\s+(?P<city>{_CITY})"
    ),
    re.compile(
        rf"\b(?P<zip>[1-9][0-9]{{3}})\s+(?P<city>{_CITY})\s*,?\s+"
        rf"(?P<street>{_STREET})\s+(?P<number>\d+[A-Za-z]?(?:/\d+[A-Za-z]?)?)"
    ),
]


def _methods(route: Any) -> set[str]:
    return set(getattr(route, "methods", set()) or set())


def _remove_route(app: FastAPI, path: str, method: str) -> None:
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (getattr(route, "path", "") == path and method in _methods(route))
    ]


def ensure_expose_review_schema() -> None:
    house_manage.ensure_house_manage_schema()
    with connect() as con:
        ensure_columns(
            con,
            "media_assets",
            {
                "display_name": "TEXT",
                "extraction_status": "TEXT",
                "extraction_summary": "TEXT",
            },
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS expose_address_proposals (
                id TEXT PRIMARY KEY,
                house_id TEXT NOT NULL,
                media_id TEXT,
                address_text TEXT NOT NULL,
                context_text TEXT,
                confidence TEXT NOT NULL DEFAULT 'medium',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                decided_at TEXT,
                FOREIGN KEY(house_id) REFERENCES houses(id),
                FOREIGN KEY(media_id) REFERENCES media_assets(id)
            )
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_expose_address_proposals_house
            ON expose_address_proposals(house_id, status, created_at)
            """
        )
        con.commit()


def _clean_city(value: str) -> str:
    city = re.sub(r"\s+", " ", value or "").strip(" ,.;:-")
    city = _CITY_STOP.split(city, maxsplit=1)[0].strip(" ,.;:-")
    return city


def extract_address_proposals(text: str) -> list[dict[str, str]]:
    flat = re.sub(r"\s+", " ", str(text or "").replace("\u00a0", " ")).strip()
    if not flat:
        return []

    proposals: list[dict[str, str]] = []
    seen: set[str] = set()
    for pattern in _ADDRESS_PATTERNS:
        for match in pattern.finditer(flat):
            street = re.sub(r"\s+", " ", match.group("street")).strip()
            number = match.group("number").strip()
            postcode = match.group("zip").strip()
            city = _clean_city(match.group("city"))
            if not city:
                continue

            address = f"{street} {number}, {postcode} {city}"
            key = re.sub(r"[^a-z0-9äöüß]", "", address.lower())
            if not key or key in seen:
                continue

            before = flat[max(0, match.start() - 150):match.start()]
            context = flat[max(0, match.start() - 170):min(len(flat), match.end() + 170)]
            positive_markers = list(_POSITIVE_CONTEXT.finditer(before))
            blocked_markers = list(_BLOCKED_CONTEXT.finditer(before))
            positive = bool(
                positive_markers
                and (not blocked_markers or positive_markers[-1].start() > blocked_markers[-1].start())
                and len(before) - positive_markers[-1].end() <= 95
            )
            blocked = bool(_BLOCKED_CONTEXT.search(context))
            if blocked and not positive:
                continue

            seen.add(key)
            proposals.append(
                {
                    "address_text": address,
                    "context_text": context[:500],
                    "confidence": "high" if positive else "medium",
                }
            )
    proposals.sort(key=lambda item: 0 if item["confidence"] == "high" else 1)
    return proposals[:5]


def store_address_proposals(
    house_id: str,
    media_id: str | None,
    proposals: list[dict[str, str]],
) -> list[dict[str, Any]]:
    ensure_expose_review_schema()
    stored: list[dict[str, Any]] = []
    timestamp = now_iso()
    with connect() as con:
        for proposal in proposals:
            address = str(proposal.get("address_text") or "").strip()
            if not address:
                continue
            existing = con.execute(
                """
                SELECT * FROM expose_address_proposals
                WHERE house_id = ?
                  AND lower(address_text) = lower(?)
                  AND status IN ('pending', 'accepted')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (house_id, address),
            ).fetchone()
            if existing:
                stored.append(row_to_dict(existing) or {})
                continue

            proposal_id = uuid.uuid4().hex[:12]
            con.execute(
                """
                INSERT INTO expose_address_proposals (
                    id, house_id, media_id, address_text, context_text,
                    confidence, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    proposal_id,
                    house_id,
                    media_id,
                    address,
                    proposal.get("context_text"),
                    proposal.get("confidence") or "medium",
                    timestamp,
                ),
            )
            row = con.execute(
                "SELECT * FROM expose_address_proposals WHERE id = ?",
                (proposal_id,),
            ).fetchone()
            stored.append(row_to_dict(row) or {})
        con.commit()
    return stored


def list_address_proposals(house_id: str) -> list[dict[str, Any]]:
    ensure_expose_review_schema()
    with connect() as con:
        rows = con.execute(
            """
            SELECT * FROM expose_address_proposals
            WHERE house_id = ?
            ORDER BY
                CASE status WHEN 'pending' THEN 0 WHEN 'accepted' THEN 1 ELSE 2 END,
                created_at DESC
            """,
            (house_id,),
        ).fetchall()
    return [row_to_dict(row) or {} for row in rows]


def _set_media_extraction(
    media_id: str,
    *,
    display_name: str | None = None,
    status: str | None = None,
    summary: str | None = None,
) -> None:
    fields: dict[str, Any] = {}
    if display_name is not None:
        fields["display_name"] = display_name
    if status is not None:
        fields["extraction_status"] = status
    if summary is not None:
        fields["extraction_summary"] = summary
    if not fields:
        return
    sql = ", ".join(f"{key} = ?" for key in fields)
    with connect() as con:
        con.execute(
            f"UPDATE media_assets SET {sql} WHERE id = ?",
            list(fields.values()) + [media_id],
        )
        con.commit()


def _pdf_text_only(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))
    parts: list[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(parts)


def process_expose_pdf(
    house_id: str,
    media_id: str,
    pdf_path: Path,
    *,
    extract_images: bool,
) -> dict[str, Any]:
    ensure_expose_review_schema()
    try:
        if extract_images:
            text, image_count = house_manage.pdf_text_and_images(house_id, pdf_path)
        else:
            text = _pdf_text_only(pdf_path)
            image_count = 0

        facts, evidence = house_manage.parse_pdf_facts(text)
        if facts:
            house_manage.update_house_details(house_id, facts)

        candidates = extract_address_proposals(text)
        stored = store_address_proposals(house_id, media_id, candidates)
        pending = [item for item in stored if item.get("status") == "pending"]
        summary = (
            f"PDF ausgelesen · {len(text)} Textzeichen · {image_count} Bilder extrahiert · "
            f"{len(pending)} Adressvorschlag/-vorschläge zur Prüfung"
        )
        evidence.append(
            {
                "field_name": "expose_pdf",
                "value": pdf_path.name,
                "source_label": "Exposé PDF",
                "source_text_snippet": summary,
                "confidence": "derived",
            }
        )
        if candidates:
            for candidate in candidates:
                evidence.append(
                    {
                        "field_name": "pdf_address_proposal",
                        "value": candidate["address_text"],
                        "source_label": "Exposé PDF – Adresse zur Freigabe",
                        "source_text_snippet": candidate.get("context_text"),
                        "confidence": candidate.get("confidence") or "medium",
                    }
                )
        add_evidence(house_id, None, evidence)
        _set_media_extraction(media_id, status="success", summary=summary)
        return {
            "facts": facts,
            "proposal_count": len(pending),
            "image_count": image_count,
            "summary": summary,
        }
    except Exception as exc:
        message = f"PDF konnte nicht vollständig ausgelesen werden: {str(exc)[:300]}"
        _set_media_extraction(media_id, status="failed", summary=message)
        add_evidence(
            house_id,
            None,
            [
                {
                    "field_name": "expose_pdf",
                    "value": pdf_path.name,
                    "source_label": "Exposé PDF",
                    "source_text_snippet": message,
                    "confidence": "unknown",
                }
            ],
        )
        return {"facts": {}, "proposal_count": 0, "image_count": 0, "summary": message}


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


def expose_documents_html(house_id: str) -> str:
    ensure_expose_review_schema()
    house = get_house(house_id) or {}
    pdfs = [
        item
        for item in list_media(house_id)
        if item.get("kind") == "pdf"
        and item.get("download_status") == "downloaded"
        and item.get("local_path")
    ]
    pdfs.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    proposals = list_address_proposals(house_id)

    document_rows: list[str] = []
    for item in pdfs:
        media_id = str(item.get("id") or "")
        name = str(item.get("display_name") or "").strip()
        if not name:
            name = Path(str(item.get("local_path") or "Exposé.pdf")).name
        status = str(item.get("extraction_status") or "gespeichert")
        summary = str(item.get("extraction_summary") or "PDF ist gespeichert und kann geöffnet werden.")
        status_class = "bad" if status == "failed" else "good" if status == "success" else ""
        document_rows.append(
            f"""
            <div class="source-card" style="margin-top:8px">
              <strong>{esc(name)}</strong>
              <p class="muted" style="margin:5px 0">{esc(_format_size(item.get('file_size_bytes')))} · {esc(format_datetime(item.get('created_at')))}</p>
              <p style="margin:5px 0"><span class="pill {status_class}">{esc(status)}</span> {esc(summary)}</p>
              <div class="action-row">
                <a class="button secondary" href="../media/{esc(media_id)}" target="_blank">PDF öffnen</a>
                <form method="post" action="{esc(house_id)}/expose/{esc(media_id)}/reprocess" data-loading="Exposé wird erneut ausgelesen …">
                  <button class="secondary" type="submit">Erneut auslesen</button>
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
                  <p style="font-size:18px;font-weight:800;margin:8px 0">{esc(proposal.get('address_text'))}</p>
                  <p class="muted">Aktuell in der Hausakte: {esc(house.get('location_text') or 'keine Adresse')} · Erkennungssicherheit: {esc(confidence_label)}</p>
                  <details>
                    <summary>Fundstelle im PDF anzeigen</summary>
                    <p class="muted">{esc(proposal.get('context_text') or 'Keine Textstelle gespeichert.')}</p>
                  </details>
                  <div class="action-row" style="margin-top:8px">
                    <form method="post" action="{esc(house_id)}/address-proposals/{esc(proposal_id)}/accept" data-loading="Adresse wird in die Hausakte übernommen …">
                      <button type="submit">Adresse übernehmen</button>
                    </form>
                    <form method="post" action="{esc(house_id)}/address-proposals/{esc(proposal_id)}/reject" data-no-loading="true">
                      <button class="secondary" type="submit">Verwerfen</button>
                    </form>
                  </div>
                </div>
                """
            )
        else:
            label = "übernommen" if status == "accepted" else "verworfen"
            css = "good" if status == "accepted" else ""
            history_html.append(
                f'<span class="pill {css}">{esc(proposal.get("address_text"))} · {label}</span>'
            )

    return f"""
    <div class="card compact-card" id="{_PATCH_MARKER}">
      <h2>Exposé und Dokumente</h2>
      <p class="muted">Hochgeladene PDFs bleiben in der Hausakte sichtbar. Eine erkannte Objektadresse wird erst nach deiner Prüfung übernommen.</p>
      {''.join(document_rows) if document_rows else '<p class="muted">Noch kein Exposé PDF gespeichert.</p>'}
      {''.join(pending_html)}
      {f'<details style="margin-top:10px"><summary><strong>Frühere Adressentscheidungen</strong></summary><p>{"".join(history_html)}</p></details>' if history_html else ''}
    </div>
    """


def _patch_diagnostics() -> None:
    current: Callable[[str], str] = product_ui.diagnostics_html
    if getattr(current, "_expose_review_patched", False):
        return

    def diagnostics_with_expose(house_id: str) -> str:
        return expose_documents_html(house_id) + current(house_id)

    setattr(diagnostics_with_expose, "_expose_review_patched", True)
    product_ui.diagnostics_html = diagnostics_with_expose


def register_expose_review(app: FastAPI) -> None:
    ensure_expose_review_schema()
    _patch_diagnostics()
    _remove_route(app, "/houses/{house_id}/expose", "POST")

    @app.post("/houses/{house_id}/expose")
    async def upload_expose_pdf_reviewed(
        house_id: str,
        file: UploadFile = File(...),
    ) -> RedirectResponse:
        if not get_house(house_id):
            raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")
        if not (file.filename or "").lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Bitte ein PDF hochladen")

        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Das PDF ist leer")

        display_name = re.sub(r"[\r\n\t]+", " ", file.filename or "expose.pdf").strip()
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", display_name) or "expose.pdf"
        stored_name = f"{uuid.uuid4().hex[:8]}_{safe_name}"
        target = project_dir(house_id) / "pdfs" / stored_name
        target.write_bytes(content)
        media = add_media(
            house_id,
            {
                "kind": "pdf",
                "local_path": str(target),
                "mime_type": file.content_type or "application/pdf",
                "download_status": "downloaded",
                "file_size_bytes": len(content),
                "content_hash": hashlib.sha256(content).hexdigest(),
            },
        )
        media_id = str(media.get("id") or "")
        _set_media_extraction(
            media_id,
            display_name=display_name,
            status="processing",
            summary="PDF wurde gespeichert und wird ausgelesen.",
        )
        process_expose_pdf(
            house_id,
            media_id,
            target,
            extract_images=True,
        )
        return RedirectResponse(f"../{house_id}", status_code=303)

    @app.post("/houses/{house_id}/expose/{media_id}/reprocess")
    async def reprocess_expose_pdf(house_id: str, media_id: str) -> RedirectResponse:
        media = get_media(media_id)
        if (
            not media
            or str(media.get("house_id") or "") != house_id
            or media.get("kind") != "pdf"
            or not media.get("local_path")
        ):
            raise HTTPException(status_code=404, detail="Exposé PDF nicht gefunden")
        path = Path(str(media.get("local_path")))
        if not path.exists():
            raise HTTPException(status_code=404, detail="PDF-Datei nicht gefunden")
        process_expose_pdf(house_id, media_id, path, extract_images=False)
        return RedirectResponse(f"../../../{house_id}", status_code=303)

    @app.post("/houses/{house_id}/address-proposals/{proposal_id}/accept")
    async def accept_address_proposal(house_id: str, proposal_id: str) -> RedirectResponse:
        ensure_expose_review_schema()
        timestamp = now_iso()
        with connect() as con:
            proposal = con.execute(
                """
                SELECT * FROM expose_address_proposals
                WHERE id = ? AND house_id = ? AND status = 'pending'
                """,
                (proposal_id, house_id),
            ).fetchone()
            if not proposal:
                raise HTTPException(status_code=404, detail="Adressvorschlag nicht gefunden")
            address = str(proposal["address_text"] or "").strip()
            con.execute(
                """
                UPDATE houses
                SET location_text = ?, exact_address = ?, address_status = 'exact', updated_at = ?
                WHERE id = ?
                """,
                (address, address, timestamp, house_id),
            )
            con.execute(
                """
                UPDATE expose_address_proposals
                SET status = 'accepted', decided_at = ?
                WHERE id = ?
                """,
                (timestamp, proposal_id),
            )
            con.execute(
                """
                UPDATE expose_address_proposals
                SET status = 'rejected', decided_at = ?
                WHERE house_id = ? AND id <> ? AND status = 'pending'
                """,
                (timestamp, house_id, proposal_id),
            )
            con.commit()
        add_evidence(
            house_id,
            None,
            [
                {
                    "field_name": "location_text",
                    "value": address,
                    "source_label": "Exposé PDF – vom Benutzer freigegeben",
                    "source_text_snippet": str(proposal["context_text"] or "")[:300],
                    "confidence": "verified",
                }
            ],
        )
        return RedirectResponse(f"../../../{house_id}", status_code=303)

    @app.post("/houses/{house_id}/address-proposals/{proposal_id}/reject")
    async def reject_address_proposal(house_id: str, proposal_id: str) -> RedirectResponse:
        ensure_expose_review_schema()
        with connect() as con:
            result = con.execute(
                """
                UPDATE expose_address_proposals
                SET status = 'rejected', decided_at = ?
                WHERE id = ? AND house_id = ? AND status = 'pending'
                """,
                (now_iso(), proposal_id, house_id),
            )
            con.commit()
        if int(result.rowcount or 0) == 0:
            raise HTTPException(status_code=404, detail="Adressvorschlag nicht gefunden")
        return RedirectResponse(f"../../../{house_id}", status_code=303)
