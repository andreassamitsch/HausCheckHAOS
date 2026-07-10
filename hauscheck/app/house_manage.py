from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import RedirectResponse
from pypdf import PdfReader

from app.parser import parse_int_eur, parse_number
from app.storage import (
    PROJECTS_DIR,
    add_evidence,
    add_media,
    connect,
    get_house,
    list_media,
    now_iso,
    project_dir,
    row_to_dict,
)
from app.ui_helpers import esc


HOUSE_UPDATE_FIELDS = {
    "title",
    "location_text",
    "address_status",
    "price_eur",
    "living_area_m2",
    "plot_area_m2",
    "rooms",
    "year_built",
    "heating",
    "energy_hwb",
    "energy_fgee",
    "energy_class_hwb",
    "energy_class_fgee",
    "notes",
    "preview_image_url",
}


def ensure_house_manage_schema() -> None:
    with connect() as con:
        rows = con.execute("PRAGMA table_info(houses)").fetchall()
        existing = {row[1] for row in rows}
        if "preview_image_url" not in existing:
            con.execute("ALTER TABLE houses ADD COLUMN preview_image_url TEXT")
        if "exact_address" not in existing:
            con.execute("ALTER TABLE houses ADD COLUMN exact_address TEXT")
        con.commit()


def clean_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text if text else None


def clean_int(value: object) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace(".", "").replace(",", ".")
    try:
        return int(float(text))
    except Exception:
        return None


def clean_float(value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except Exception:
        return None


def update_house_details(house_id: str, data: dict[str, Any]) -> dict[str, Any]:
    ensure_house_manage_schema()
    fields = {key: value for key, value in data.items() if key in HOUSE_UPDATE_FIELDS}
    if not fields:
        house = get_house(house_id)
        return house or {}

    fields["updated_at"] = now_iso()
    sql = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [house_id]
    with connect() as con:
        con.execute(f"UPDATE houses SET {sql} WHERE id = ?", values)
        con.commit()
        row = con.execute("SELECT * FROM houses WHERE id = ?", (house_id,)).fetchone()
    return row_to_dict(row) or {}


def set_house_preview(house_id: str, preview_image_url: str | None) -> None:
    if not preview_image_url:
        return
    update_house_details(house_id, {"preview_image_url": str(preview_image_url).strip()})


def delete_house_full(house_id: str) -> None:
    house = get_house(house_id)
    if not house:
        raise ValueError("Hausakte nicht gefunden")
    with connect() as con:
        con.execute("DELETE FROM field_evidence WHERE house_id = ?", (house_id,))
        con.execute("DELETE FROM media_assets WHERE house_id = ?", (house_id,))
        con.execute("DELETE FROM listing_sources WHERE house_id = ?", (house_id,))
        con.execute("UPDATE search_candidates SET status = 'new', imported_house_id = NULL WHERE imported_house_id = ?", (house_id,))
        con.execute("DELETE FROM houses WHERE id = ?", (house_id,))
        con.commit()

    path = PROJECTS_DIR / house_id
    try:
        path.relative_to(PROJECTS_DIR)
        if path.exists():
            shutil.rmtree(path)
    except Exception:
        pass


def first_local_image_id(house_id: str) -> str | None:
    for item in list_media(house_id):
        if item.get("kind") == "image" and item.get("download_status") == "downloaded" and item.get("local_path"):
            return str(item.get("id"))
    return None


def dashboard_preview_html(house: dict[str, Any]) -> str:
    preview = str(house.get("preview_image_url") or "").strip()
    if preview:
        return f'<img class="thumb" src="{esc(preview)}" alt="Vorschaubild">'
    media_id = first_local_image_id(str(house.get("id") or ""))
    if media_id:
        return f'<img class="thumb" src="media/{esc(media_id)}" alt="Bild">'
    return '<div class="muted">Noch kein Bild</div>'


def gallery_slider_html(house_id: str) -> str:
    items = []
    for item in list_media(house_id):
        if item.get("kind") == "image" and item.get("download_status") == "downloaded":
            mid = esc(item.get("id"))
            items.append(
                f"""
                <a class="gallery-slide" href="../media/{mid}" target="_blank">
                  <img src="../media/{mid}" alt="Bild">
                </a>
                """
            )
    if not items:
        return "<p class='muted'>Noch keine heruntergeladenen Bilder.</p>"
    return f"<div class='gallery-slider'>{''.join(items)}</div>"


def edit_house_form_html(house: dict[str, Any]) -> str:
    hid = esc(house.get("id"))
    return f"""
    <div class="card compact-card">
      <details>
        <summary><strong>Hausakte bearbeiten</strong></summary>
        <form method="post" action="{hid}/edit" data-loading="Hausakte wird aktualisiert …">
          <label>Titel</label>
          <input name="title" value="{esc(house.get('title'))}">
          <label>Adresse / Lage</label>
          <input name="location_text" value="{esc(house.get('location_text'))}" placeholder="z. B. Straße Hausnummer, PLZ Ort">
          <label>Adressstatus</label>
          <select name="address_status">
            <option value="unknown" {'selected' if house.get('address_status') == 'unknown' else ''}>unbekannt</option>
            <option value="municipality_only" {'selected' if house.get('address_status') == 'municipality_only' else ''}>nur Ort/Gemeinde</option>
            <option value="hint" {'selected' if house.get('address_status') == 'hint' else ''}>Adresshinweis</option>
            <option value="exact" {'selected' if house.get('address_status') == 'exact' else ''}>genaue Adresse</option>
          </select>
          <div class="grid">
            <div><label>Preis €</label><input name="price_eur" type="number" value="{esc(house.get('price_eur'))}"></div>
            <div><label>Wohnfläche m²</label><input name="living_area_m2" type="number" step="0.1" value="{esc(house.get('living_area_m2'))}"></div>
            <div><label>Grundstück m²</label><input name="plot_area_m2" type="number" step="0.1" value="{esc(house.get('plot_area_m2'))}"></div>
            <div><label>Zimmer</label><input name="rooms" type="number" step="0.1" value="{esc(house.get('rooms'))}"></div>
            <div><label>Baujahr</label><input name="year_built" type="number" value="{esc(house.get('year_built'))}"></div>
            <div><label>HWB</label><input name="energy_hwb" type="number" step="0.1" value="{esc(house.get('energy_hwb'))}"></div>
            <div><label>fGEE</label><input name="energy_fgee" type="number" step="0.01" value="{esc(house.get('energy_fgee'))}"></div>
            <div><label>Heizung</label><input name="heating" value="{esc(house.get('heating'))}"></div>
          </div>
          <label>Portal-Vorschaubild URL</label>
          <input name="preview_image_url" value="{esc(house.get('preview_image_url'))}">
          <label>Notizen</label>
          <textarea name="notes" rows="3">{esc(house.get('notes'))}</textarea>
          <button type="submit">Speichern</button>
        </form>
      </details>
    </div>
    """


def delete_house_form_html(house_id: str) -> str:
    hid = esc(house_id)
    return f"""
    <div class="card compact-card danger-zone">
      <details>
        <summary><strong>Hausakte löschen</strong></summary>
        <p class="muted">Löscht Hausakte, Quellen, Medien, Analysen und den Projektordner unter /share/hauscheck/projects/{hid}.</p>
        <form method="post" action="{hid}/delete" data-loading="Hausakte und Daten werden gelöscht …" onsubmit="return confirm('Hausakte inklusive aller geladenen Daten wirklich löschen?');">
          <button class="danger" type="submit">Hausakte endgültig löschen</button>
        </form>
      </details>
    </div>
    """


def expose_upload_html(house_id: str) -> str:
    hid = esc(house_id)
    return f"""
    <div class="card compact-card">
      <h2>Exposé PDF</h2>
      <p class="muted">PDF hochladen. HausCheck liest Textdaten aus und ergänzt erkannte Werte wie Adresse, Preis, Flächen, HWB, fGEE, Heizung und Baujahr. Bilder aus PDFs werden soweit technisch möglich extrahiert.</p>
      <form method="post" action="{hid}/expose" enctype="multipart/form-data" data-loading="Exposé wird hochgeladen und ausgewertet …">
        <input type="file" name="file" accept=".pdf,application/pdf" required>
        <button type="submit">Exposé hochladen & auslesen</button>
      </form>
    </div>
    """


def parse_pdf_facts(text: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    facts: dict[str, Any] = {}
    evidence: list[dict[str, Any]] = []

    def add(field: str, value: Any, label: str, snippet: str, confidence: str = "derived") -> None:
        if value is None or value == "":
            return
        facts[field] = value
        evidence.append({"field_name": field, "value": value, "source_label": label, "source_text_snippet": snippet[:300], "confidence": confidence})

    price = parse_int_eur(text)
    if price:
        add("price_eur", price, "Exposé PDF Preis", "Preis/€ im PDF", "derived")

    patterns = {
        "living_area_m2": [r"Wohnfläche\s*[:\-]?\s*([0-9][0-9\.,\s]*)\s*m", r"Wohnnutzfläche\s*[:\-]?\s*([0-9][0-9\.,\s]*)\s*m"],
        "plot_area_m2": [r"Grundstücksfläche\s*[:\-]?\s*([0-9][0-9\.,\s]*)\s*m", r"Grundfläche\s*[:\-]?\s*([0-9][0-9\.,\s]*)\s*m"],
        "rooms": [r"Zimmer\s*[:\-]?\s*([0-9][0-9\.,]*)"],
        "energy_hwb": [r"HWB[^0-9]{0,40}([0-9]+(?:[\.,][0-9]+)?)"],
        "energy_fgee": [r"f\s*\{?GEE\}?[^0-9]{0,40}([0-9]+(?:[\.,][0-9]+)?)"],
    }
    for field, regs in patterns.items():
        for reg in regs:
            match = re.search(reg, text, re.IGNORECASE)
            if match:
                add(field, parse_number(match.group(1)), f"Exposé PDF {field}", match.group(0), "derived")
                break

    year_match = re.search(r"Baujahr\s*[:\-]?\s*([12][0-9]{3})", text, re.IGNORECASE)
    if year_match:
        add("year_built", int(year_match.group(1)), "Exposé PDF Baujahr", year_match.group(0), "derived")

    heating_match = re.search(r"(?:Heizung|Heizungsart)\s*[:\-]?\s*([A-Za-zÄÖÜäöüß /\-]+?)(?:\s{2,}|HWB|fGEE|Energie|Baujahr|Zimmer|$)", text, re.IGNORECASE)
    if heating_match:
        add("heating", heating_match.group(1).strip()[:120], "Exposé PDF Heizung", heating_match.group(0), "derived")

    # Adresshinweis: exakte Adressen können im PDF stehen, werden aber als abgeleitet markiert.
    addr_patterns = [
        r"((?:[A-ZÄÖÜ][A-Za-zÄÖÜäöüß\-]+(?:straße|gasse|weg|platz|allee|ring|dorf|berg|siedlung))\s+\d+[A-Za-z]?,?\s*[0-9]{4}\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß\- ]{2,60})",
        r"([0-9]{4}\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß\- ]{2,60})",
    ]
    for reg in addr_patterns:
        match = re.search(reg, text)
        if match:
            add("location_text", match.group(1).strip(), "Exposé PDF Adress-/Ortsangabe", match.group(0), "derived")
            facts["address_status"] = "hint" if not re.search(r"\d+[A-Za-z]?,?\s*[0-9]{4}", match.group(1)) else "exact"
            break

    return facts, evidence


def pdf_text_and_images(house_id: str, pdf_path: Path) -> tuple[str, int]:
    reader = PdfReader(str(pdf_path))
    text_parts: list[str] = []
    image_count = 0
    hdir = project_dir(house_id)
    for page_index, page in enumerate(reader.pages, start=1):
        try:
            text_parts.append(page.extract_text() or "")
        except Exception:
            pass
        try:
            for img_index, image in enumerate(page.images, start=1):
                data = image.data
                ext = Path(image.name or "image.jpg").suffix.lower() or ".jpg"
                if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
                    ext = ".jpg"
                filename = f"expose_p{page_index:02d}_{img_index:02d}_{uuid.uuid4().hex[:6]}{ext}"
                target = hdir / "images" / filename
                target.write_bytes(data)
                add_media(house_id, {"kind": "image", "local_path": str(target), "mime_type": f"image/{ext.lstrip('.')}", "download_status": "downloaded", "file_size_bytes": len(data)})
                image_count += 1
        except Exception:
            pass
    return "\n".join(text_parts), image_count


def register_house_management(app: FastAPI) -> None:
    ensure_house_manage_schema()

    @app.post("/houses/{house_id}/edit")
    async def edit_house(
        house_id: str,
        title: str | None = Form(None),
        location_text: str | None = Form(None),
        address_status: str | None = Form("unknown"),
        price_eur: str | None = Form(None),
        living_area_m2: str | None = Form(None),
        plot_area_m2: str | None = Form(None),
        rooms: str | None = Form(None),
        year_built: str | None = Form(None),
        heating: str | None = Form(None),
        energy_hwb: str | None = Form(None),
        energy_fgee: str | None = Form(None),
        preview_image_url: str | None = Form(None),
        notes: str | None = Form(None),
    ) -> RedirectResponse:
        if not get_house(house_id):
            raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")
        update_house_details(
            house_id,
            {
                "title": clean_text(title),
                "location_text": clean_text(location_text),
                "address_status": clean_text(address_status) or "unknown",
                "price_eur": clean_int(price_eur),
                "living_area_m2": clean_float(living_area_m2),
                "plot_area_m2": clean_float(plot_area_m2),
                "rooms": clean_float(rooms),
                "year_built": clean_int(year_built),
                "heating": clean_text(heating),
                "energy_hwb": clean_float(energy_hwb),
                "energy_fgee": clean_float(energy_fgee),
                "preview_image_url": clean_text(preview_image_url),
                "notes": clean_text(notes),
            },
        )
        return RedirectResponse(f"../{house_id}", status_code=303)

    @app.post("/houses/{house_id}/delete")
    async def delete_house_route(house_id: str) -> RedirectResponse:
        try:
            delete_house_full(house_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return RedirectResponse("../../", status_code=303)

    @app.post("/houses/{house_id}/expose")
    async def upload_expose_pdf(house_id: str, file: UploadFile = File(...)) -> RedirectResponse:
        house = get_house(house_id)
        if not house:
            raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")
        if not (file.filename or "").lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Bitte ein PDF hochladen")

        content = await file.read()
        filename = re.sub(r"[^A-Za-z0-9._-]", "_", file.filename or "expose.pdf")
        target = project_dir(house_id) / "pdfs" / filename
        target.write_bytes(content)
        add_media(house_id, {"kind": "pdf", "local_path": str(target), "mime_type": file.content_type or "application/pdf", "download_status": "downloaded", "file_size_bytes": len(content)})

        try:
            text, image_count = pdf_text_and_images(house_id, target)
            facts, evidence = parse_pdf_facts(text)
            if facts:
                update_house_details(house_id, facts)
            evidence.append({"field_name": "expose_pdf", "value": filename, "source_label": "Exposé PDF", "source_text_snippet": f"PDF ausgelesen. Extrahierte Bilder: {image_count}", "confidence": "derived"})
            add_evidence(house_id, None, evidence)
        except Exception as exc:
            add_evidence(house_id, None, [{"field_name": "expose_pdf", "value": filename, "source_label": "Exposé PDF", "source_text_snippet": f"PDF konnte nicht vollständig ausgelesen werden: {str(exc)[:300]}", "confidence": "unknown"}])

        return RedirectResponse(f"../{house_id}", status_code=303)
