from __future__ import annotations

import io
import json
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from PIL import Image, UnidentifiedImageError

from app.storage import PROJECTS_DIR, get_house, list_evidence, list_media, list_sources, project_dir


ANALYSIS_FILENAME = "hauscheck_analysis.json"
EXPORT_IMAGE_LIMIT = 12
EXPORT_IMAGE_MAX_SIZE = 1600


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def esc(value: object) -> str:
    import html

    if value is None:
        return ""
    return html.escape(str(value))


def safe_name(value: object, fallback: str = "haus") -> str:
    text = str(value or fallback).strip().lower()
    text = re.sub(r"[^a-z0-9äöüß._ -]+", "", text)
    text = text.replace(" ", "_")
    text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return (text or fallback)[:80]


def analysis_path(house_id: str) -> Path:
    return project_dir(house_id) / "analysis" / ANALYSIS_FILENAME


def load_analysis(house_id: str) -> dict[str, Any] | None:
    path = analysis_path(house_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_analysis(house_id: str, data: dict[str, Any]) -> Path:
    house = get_house(house_id)
    if not house:
        raise ValueError("Hausakte nicht gefunden")
    if str(data.get("house_id") or "") != house_id:
        raise ValueError("house_id in der Analyse passt nicht zu dieser Hausakte")

    target = analysis_path(house_id)
    if target.exists():
        backup = target.with_name(f"hauscheck_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        shutil.copyfile(target, backup)

    data.setdefault("analysis_date", now_iso())
    data.setdefault("source", "manual_chatgpt_upload")
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def public_house(house: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "id",
        "title",
        "status",
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
        "created_at",
        "updated_at",
    ]
    return {key: house.get(key) for key in keys}


def source_export(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_name": source.get("source_name"),
        "source_url": source.get("source_url"),
        "external_id": source.get("external_id"),
        "description": source.get("description"),
        "parser_status": source.get("parser_status"),
        "parser_warnings": source.get("parser_warnings"),
    }


def evidence_export(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "field_name": item.get("field_name"),
        "value_text": item.get("value_text"),
        "source_label": item.get("source_label"),
        "source_text_snippet": item.get("source_text_snippet"),
        "confidence": item.get("confidence"),
    }


def local_image_paths(house_id: str) -> list[tuple[dict[str, Any], Path]]:
    result: list[tuple[dict[str, Any], Path]] = []
    for media in list_media(house_id):
        if media.get("kind") != "image" or media.get("download_status") != "downloaded" or not media.get("local_path"):
            continue
        path = Path(str(media.get("local_path")))
        try:
            path.relative_to(PROJECTS_DIR)
        except ValueError:
            continue
        if path.exists() and path.is_file():
            result.append((media, path))
    result.sort(key=lambda pair: int(pair[0].get("file_size_bytes") or 0), reverse=True)
    return result


def resized_jpeg_bytes(path: Path, max_size: int = EXPORT_IMAGE_MAX_SIZE) -> bytes:
    try:
        with Image.open(path) as image:
            image = image.convert("RGB")
            image.thumbnail((max_size, max_size))
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=84, optimize=True)
            return output.getvalue()
    except UnidentifiedImageError:
        return path.read_bytes()


def analysis_schema(house_id: str) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["house_id", "analysis_date", "new_score", "confidence", "summary", "recommendation"],
        "properties": {
            "house_id": {"const": house_id},
            "analysis_date": {"type": "string", "description": "ISO-Datum oder ISO-Zeitpunkt"},
            "new_score": {"type": "integer", "minimum": 0, "maximum": 100},
            "confidence": {"enum": ["niedrig", "mittel", "hoch"]},
            "summary": {"type": "string"},
            "positive_findings": {"type": "array", "items": {"type": "string"}},
            "risk_findings": {"type": "array", "items": {"type": "string"}},
            "estimated_investment_eur": {
                "type": "object",
                "properties": {
                    "low": {"type": ["integer", "null"]},
                    "high": {"type": ["integer", "null"]},
                    "confidence": {"enum": ["niedrig", "mittel", "hoch"]},
                    "comment": {"type": "string"},
                },
            },
            "image_findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "image": {"type": "string"},
                        "area": {"type": "string"},
                        "condition": {"type": "string"},
                        "positive": {"type": "array", "items": {"type": "string"}},
                        "risks": {"type": "array", "items": {"type": "string"}},
                        "confidence": {"enum": ["niedrig", "mittel", "hoch"]},
                    },
                },
            },
            "recommendation": {"type": "string"},
            "next_steps": {"type": "array", "items": {"type": "string"}},
            "score_reasoning": {"type": "string"},
            "limitations": {"type": "array", "items": {"type": "string"}},
        },
    }


def readme_prompt(house_id: str) -> str:
    return f"""# HausCheck Analysepaket

Du bist mein Immobilienanalyse-Assistent für Hauskauf in der Südweststeiermark.
Analysiere die Dateien in diesem ZIP-Paket:

- `listing.json`: erkannte Inseratsdaten und Quellen
- `evidence.json`: Feldherkunft / Parsing-Hinweise
- `images/*.jpg`: exportierte Inseratbilder
- `current_score.json`: bisherige regelbasierte Bewertung
- `import_schema.json`: gewünschtes Rückgabeformat

## Aufgabe

Bewerte das Objekt anhand von Inseratdaten und Bildern. Trenne immer:

- gesichert: aus Daten/Bildern klar erkennbar
- abgeleitet: plausibel, aber nicht sicher
- unsicher: nicht beurteilbar

Bitte erfinde keine fehlenden Werte. Keine rechtliche/bautechnische Sicherheit vortäuschen.

## Ergebnisdatei

Erstelle am Ende eine Datei mit exakt diesem Namen:

```text
hauscheck_analysis.json
```

Die Datei muss valides JSON sein und zu `import_schema.json` passen.

Wichtig:

```json
{{
  "house_id": "{house_id}",
  "analysis_date": "{now_iso()}",
  "new_score": 0,
  "confidence": "niedrig",
  "summary": "...",
  "positive_findings": [],
  "risk_findings": [],
  "estimated_investment_eur": {{
    "low": null,
    "high": null,
    "confidence": "niedrig",
    "comment": "..."
  }},
  "image_findings": [],
  "recommendation": "...",
  "next_steps": [],
  "score_reasoning": "...",
  "limitations": []
}}
```

## Bewertungslogik

Der Score ist 0 bis 100:

- 82-100: sehr interessant
- 68-81: interessant
- 50-67: prüfen
- 0-49: kritisch

Berücksichtige besonders:

- sichtbarer Modernisierungsgrad
- Zustand Küche, Bad, Böden, Wände, Fenster, Fassade, Dach soweit sichtbar
- Feuchtigkeit/Schimmelverdacht nur als Verdacht kennzeichnen
- Energie/HWB nur aus Daten übernehmen, nicht aus Bildern schätzen
- Investitionsbedarf nur grob und mit Sicherheit angeben
- Besichtigungsfragen und nächste Prüfpunkte
"""


def current_score_data(house: dict[str, Any]) -> dict[str, Any]:
    # Einfacher Export des bestehenden Regel-Scores aus Fakten. Die UI kann separat einen erweiterten Score anzeigen.
    known = len([key for key in ["price_eur", "living_area_m2", "plot_area_m2", "energy_hwb"] if house.get(key) not in (None, "")])
    return {
        "rule_score_available": True,
        "known_core_values": known,
        "score_note": "Der sichtbare Regel-Score in HausCheck basiert auf Preis, Wohnfläche, Grundstück, HWB und Status. ChatGPT soll den KI-Score eigenständig anhand Daten und Bildern neu begründen.",
        "facts": {
            "price_eur": house.get("price_eur"),
            "living_area_m2": house.get("living_area_m2"),
            "plot_area_m2": house.get("plot_area_m2"),
            "energy_hwb": house.get("energy_hwb"),
            "status": house.get("status"),
        },
    }


def create_analysis_zip(house_id: str) -> Path:
    house = get_house(house_id)
    if not house:
        raise ValueError("Hausakte nicht gefunden")

    hdir = project_dir(house_id)
    export_dir = hdir / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    filename = f"hauscheck_export_{house_id}_{safe_name(house.get('title'))}.zip"
    target = export_dir / filename

    sources = [source_export(source) for source in list_sources(house_id)]
    evidence = [evidence_export(item) for item in list_evidence(house_id)]
    media = list_media(house_id)
    downloaded_images = local_image_paths(house_id)[:EXPORT_IMAGE_LIMIT]
    image_manifest = []

    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README_PROMPT.md", readme_prompt(house_id))
        zf.writestr(
            "listing.json",
            json.dumps({"house": public_house(house), "sources": sources, "media_count": len(media)}, ensure_ascii=False, indent=2),
        )
        zf.writestr("evidence.json", json.dumps({"evidence": evidence}, ensure_ascii=False, indent=2))
        zf.writestr("current_score.json", json.dumps(current_score_data(house), ensure_ascii=False, indent=2))
        zf.writestr("import_schema.json", json.dumps(analysis_schema(house_id), ensure_ascii=False, indent=2))
        zf.writestr("original/source_urls.txt", "\n".join(str(source.get("source_url") or "") for source in sources))

        for index, (media_item, image_path) in enumerate(downloaded_images, start=1):
            image_name = f"images/{index:02d}.jpg"
            try:
                zf.writestr(image_name, resized_jpeg_bytes(image_path))
                image_manifest.append(
                    {
                        "file": image_name,
                        "media_id": media_item.get("id"),
                        "original_url": media_item.get("original_url"),
                        "width": media_item.get("width"),
                        "height": media_item.get("height"),
                        "file_size_bytes": media_item.get("file_size_bytes"),
                    }
                )
            except Exception as exc:
                image_manifest.append({"file": image_name, "media_id": media_item.get("id"), "error": str(exc)[:300]})
        zf.writestr("image_manifest.json", json.dumps({"images": image_manifest}, ensure_ascii=False, indent=2))

    return target


def extract_analysis_json_from_upload(filename: str, content: bytes) -> dict[str, Any]:
    lower = (filename or "").lower()
    if lower.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(content), "r") as zf:
            candidates = [name for name in zf.namelist() if name.endswith(ANALYSIS_FILENAME)]
            if not candidates:
                raise ValueError(f"{ANALYSIS_FILENAME} im ZIP nicht gefunden")
            raw = zf.read(candidates[0]).decode("utf-8")
    else:
        raw = content.decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Analyse-Datei muss ein JSON-Objekt enthalten")
    return data


def analysis_status_html(house_id: str) -> str:
    analysis = load_analysis(house_id)
    if analysis:
        score = analysis.get("new_score")
        confidence = analysis.get("confidence") or "unbekannt"
        date = analysis.get("analysis_date") or "unbekannt"
        summary = analysis.get("summary") or "Keine Zusammenfassung vorhanden."
        recommendation = analysis.get("recommendation") or ""
        risks = analysis.get("risk_findings") or []
        positives = analysis.get("positive_findings") or []
        positive_html = "".join(f"<li>{esc(item)}</li>" for item in positives[:6]) or "<li class='muted'>Keine positiven Befunde importiert.</li>"
        risk_html = "".join(f"<li>{esc(item)}</li>" for item in risks[:6]) or "<li class='muted'>Keine Risiken importiert.</li>"
        analysis_html = f"""
        <p><span class="pill good">KI-Score {esc(score)}/100</span><span class="pill">Sicherheit: {esc(confidence)}</span><span class="pill">Analyse: {esc(date)}</span></p>
        <p>{esc(summary)}</p>
        <p><strong>Empfehlung:</strong> {esc(recommendation)}</p>
        <div class="grid"><div><strong>Chancen</strong><ul>{positive_html}</ul></div><div><strong>Risiken</strong><ul>{risk_html}</ul></div></div>
        """
    else:
        analysis_html = "<p class='muted'>Noch keine importierte ChatGPT-Analyse vorhanden.</p>"

    return f"""
    <div class="card">
      <h2>ChatGPT-Analyse</h2>
      {analysis_html}
      <a class="button" href="{house_id}/analysis/export">Analysepaket exportieren</a>
      <form method="post" action="{house_id}/analysis/import" enctype="multipart/form-data" data-loading="ChatGPT-Analyse wird importiert …" style="margin-top:12px">
        <label>hauscheck_analysis.json oder ZIP mit hauscheck_analysis.json importieren</label>
        <input type="file" name="file" accept=".json,.zip,application/json,application/zip" required>
        <button class="secondary" type="submit">KI-Analyse importieren</button>
      </form>
      <p class="muted">Workflow: ZIP exportieren → in ChatGPT hochladen → hauscheck_analysis.json zurück importieren.</p>
    </div>
    """


def register_analysis_package(app: FastAPI) -> None:
    @app.get("/houses/{house_id}/analysis/export")
    async def export_analysis_package(house_id: str) -> FileResponse:
        try:
            path = create_analysis_zip(house_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(path, media_type="application/zip", filename=path.name)

    @app.post("/houses/{house_id}/analysis/import")
    async def import_analysis(house_id: str, file: UploadFile = File(...)) -> RedirectResponse:
        if not get_house(house_id):
            raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")
        try:
            content = await file.read()
            data = extract_analysis_json_from_upload(file.filename or "hauscheck_analysis.json", content)
            save_analysis(house_id, data)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Analyse konnte nicht importiert werden: {str(exc)[:500]}") from exc
        return RedirectResponse(f"../../{house_id}", status_code=303)

    @app.get("/houses/{house_id}/analysis/json")
    async def analysis_json(house_id: str) -> dict[str, Any]:
        if not get_house(house_id):
            raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")
        return load_analysis(house_id) or {"house_id": house_id, "analysis": None}
