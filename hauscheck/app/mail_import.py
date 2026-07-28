from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from email import policy
from email.message import Message
from email.parser import BytesParser
from pathlib import Path
from typing import Any, Iterable

from bs4 import BeautifulSoup
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader

import app.main as main
import app.modern_ui as modern_ui
from app.github_auto_export import auto_export_house_to_github
from app.pipeline_status import set_pipeline_stage
from app.storage import (
    DATA_DIR,
    add_evidence,
    add_media,
    create_house,
    create_source,
    find_media_by_hash,
    get_house,
    now_iso,
    project_dir,
)
from app.ui_helpers import esc


IMPORT_ROOT = DATA_DIR / "mail_imports"
MAX_UPLOADS = 40
MAX_FILE_BYTES = 30 * 1024 * 1024
MAX_TOTAL_BYTES = 140 * 1024 * 1024
SESSION_MAX_AGE_SECONDS = 48 * 60 * 60
ALLOWED_EXTENSIONS = {".eml", ".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
CONFIDENCE_RANK = {"low": 1, "medium": 2, "high": 3, "verified": 4}
FIELD_NAMES = {
    "title",
    "location_text",
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
}


@dataclass
class SavedInput:
    filename: str
    path: Path
    mime_type: str
    source_key: str
    source_label: str


def _methods(route: Any) -> set[str]:
    return set(getattr(route, "methods", set()) or set())


def _remove_route(app: FastAPI, path: str, method: str) -> None:
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (getattr(route, "path", "") == path and method in _methods(route))
    ]


def _safe_filename(value: str | None, fallback: str = "upload.bin") -> str:
    name = Path(str(value or fallback).replace("\\", "/")).name
    name = re.sub(r"[^A-Za-z0-9ÄÖÜäöüß._ -]", "_", name).strip(" .")
    return (name or fallback)[:180]


def _unique_target(directory: Path, filename: str) -> Path:
    filename = _safe_filename(filename)
    target = directory / filename
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    for index in range(2, 1000):
        candidate = directory / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
    return directory / f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _normalize_space(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_compare(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", _normalize_space(value).casefold())


def _number(value: str | None) -> float | None:
    raw = str(value or "").strip().replace("\u00a0", "").replace(" ", "")
    if not raw:
        return None
    raw = re.sub(r"[^0-9,.-]", "", raw)
    if not raw:
        return None
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", raw):
        raw = raw.replace(".", "")
    try:
        return float(raw)
    except ValueError:
        return None


def _int_number(value: str | None) -> int | None:
    parsed = _number(value)
    return int(round(parsed)) if parsed is not None else None


def _html_to_text(value: str) -> str:
    return BeautifulSoup(value or "", "html.parser").get_text("\n", strip=True)


def _header(message: Message, name: str) -> str:
    return _normalize_space(message.get(name, ""))


def _message_key(message: Message, content_hash: str) -> str:
    message_id = _header(message, "Message-ID").strip("<>")
    return f"email:{message_id or content_hash[:20]}"


def _email_source_label(message: Message, fallback: str) -> str:
    subject = _header(message, "Subject") or fallback
    sender = _header(message, "From")
    return f"E-Mail „{subject}“{f' von {sender}' if sender else ''}"


def _looks_like_signature_image(filename: str, width: int | None, height: int | None, size: int) -> bool:
    lowered = filename.casefold()
    if any(token in lowered for token in ("logo", "signature", "facebook", "instagram", "linkedin", "icon")):
        return True
    if width and height and (width < 360 or height < 220 or width * height < 120_000):
        return True
    return size < 18_000


def _image_dimensions(content: bytes) -> tuple[int | None, int | None]:
    try:
        from io import BytesIO

        with Image.open(BytesIO(content)) as image:
            return image.size
    except (UnidentifiedImageError, OSError, ValueError):
        return None, None


def _extract_pdf_text(path: Path) -> tuple[str, int, list[str]]:
    warnings: list[str] = []
    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        return "", 0, [f"PDF konnte nicht geöffnet werden: {str(exc)[:180]}"]
    pages: list[str] = []
    for index, page in enumerate(reader.pages[:80], start=1):
        try:
            pages.append(page.extract_text() or "")
        except Exception as exc:
            warnings.append(f"Seite {index} konnte nicht gelesen werden: {str(exc)[:120]}")
    text = "\n".join(pages).strip()
    if len(_normalize_space(text)) < 40:
        warnings.append("Bild-/Scan-PDF ohne ausreichend eingebetteten Text; Inhalte werden in der anschließenden KI-Analyse geprüft.")
    return text[:800_000], len(reader.pages), warnings


def _classify_document(filename: str, text: str) -> str:
    haystack = f"{filename}\n{text[:20000]}".casefold()
    basename = Path(filename).name.casefold()
    if any(token in haystack for token in ("nebenkostenübersicht", "nebenkostenuebersicht", "övi-form", "maklerprovision")) or basename.startswith(("nkü", "nkue")):
        return "Allgemeine Kaufnebenkosten-Information"
    if basename in {"ea.pdf", "energieausweis.pdf"} or any(token in haystack for token in ("energieausweis", "heizwärmebedarf", "hwb ref", "fgee")):
        return "Energieausweis"
    if any(token in haystack for token in ("grundbuch", "katastralgemeinde", "einlagezahl", "gst-nr")):
        return "Grundbuchauszug"
    if any(token in haystack for token in ("flächenwidmung", "flaechenwidmung", "flwid", "digitaler atlas steiermark")):
        return "Flächenwidmung"
    if any(token in haystack for token in ("luftbild", "orthofoto", "orthophoto")):
        return "Luftbild/Kataster"
    if filename.casefold().endswith(".pdf"):
        return "Sonstiges PDF"
    if Path(filename).suffix.casefold() in IMAGE_EXTENSIONS:
        return "Objektfoto"
    if filename.casefold().endswith(".eml"):
        return "Original-E-Mail"
    return "Sonstiges Dokument"


def _evidence(field: str, value: Any, source_key: str, source_label: str, snippet: str, confidence: str) -> dict[str, Any]:
    return {
        "field_name": field,
        "value": value,
        "source_key": source_key,
        "source_label": source_label,
        "source_text_snippet": _normalize_space(snippet)[:500],
        "confidence": confidence,
    }


def _matches(pattern: str, text: str, flags: int = re.IGNORECASE | re.MULTILINE) -> list[re.Match[str]]:
    return list(re.finditer(pattern, text or "", flags))


def _extract_evidence(text: str, classification: str, source_key: str, source_label: str) -> list[dict[str, Any]]:
    if classification == "Allgemeine Kaufnebenkosten-Information":
        return []
    items: list[dict[str, Any]] = []
    normalized = text.replace("\r", "\n")

    address_patterns = [
        r"(?:GST-ADRESSE|Objektadresse|Adresse|Anschrift|Straße)\s*[:\-]?\s*([A-ZÄÖÜ][^\n,;]{1,70}?\s\d+[A-Za-z]?)\s*[, ]+\s*(\d{4})\s+([A-ZÄÖÜ][A-Za-zÄÖÜäöüß .\-]{1,45})",
        r"\b([A-ZÄÖÜ][A-Za-zÄÖÜäöüß.\-]+(?:\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß.\-]+){0,3}\s+\d+[A-Za-z]?)\s*,\s*([A-ZÄÖÜ][A-Za-zÄÖÜäöüß.\-]+(?:\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß.\-]+){0,3})\s+(\d{4})\b",
    ]
    for pattern_index, pattern in enumerate(address_patterns):
        for match in _matches(pattern, normalized):
            if pattern_index == 0:
                street, postcode, town = match.group(1), match.group(2), match.group(3)
            else:
                street, town, postcode = match.group(1), match.group(2), match.group(3)
            street = _normalize_space(street)
            town = _normalize_space(town)
            if any(token in street.casefold() for token in ("seite ", "anteil", "geb:", "einlagezahl", "bezirksgericht")):
                continue
            address = f"{street}, {postcode} {town}"
            items.append(_evidence("location_text", address, source_key, source_label, match.group(0), "high" if classification == "Grundbuchauszug" else "medium"))

    groundbook_address = _matches(r"(?:Sonst\([^\n]*\)\s+\d+\s+)([A-ZÄÖÜ][A-Za-zÄÖÜäöüß.\- ]+\s+\d+[A-Za-z]?)", normalized)
    for match in groundbook_address:
        items.append(_evidence("location_text", _normalize_space(match.group(1)), source_key, source_label, match.group(0), "high"))

    for match in _matches(r"(?:KATASTRALGEMEINDE|KG(?:-Nr\.?| Nr\.?)?)\s*[:\-]?\s*(\d{5})\s+([A-Za-zÄÖÜäöüß.\- ]+)", normalized):
        value = f"KG {match.group(1)} {_normalize_space(match.group(2).split('EINLAGEZAHL')[0])}"
        items.append(_evidence("cadastral_community", value, source_key, source_label, match.group(0), "high"))
    for match in _matches(r"(?:EINLAGEZAHL|\bEZ\b)\s*[:\-]?\s*(\d+)", normalized):
        items.append(_evidence("land_register_ez", match.group(1), source_key, source_label, match.group(0), "high"))
    for match in _matches(r"(?:GST-NR|Grundstück(?:snummer)?|Gst\.?\s*Nr\.?)\s*[:\-]?\s*([.]?\d+(?:/\d+)?)", normalized):
        items.append(_evidence("parcel_number", match.group(1), source_key, source_label, match.group(0), "high"))

    area_matches = _matches(r"GST-Fläche\s+([\d .]{2,12})", normalized)
    if not area_matches:
        area_matches = _matches(r"(?:Gesamtfläche|Grundstücksfläche|Grundfläche)\s*[:\-]?\s*([\d .]{2,12})\s*(?:m²|m2)?", normalized)
    for match in area_matches:
        value = _number(match.group(1))
        if value and 30 <= value <= 5_000_000:
            items.append(_evidence("plot_area_m2", value, source_key, source_label, match.group(0), "high" if classification == "Grundbuchauszug" else "medium"))

    numeric_patterns: list[tuple[str, str, str]] = [
        ("living_area_m2", r"(?:Wohnfläche|Nutzfläche|Bezugsfläche)\s*[:\-]?\s*([\d., ]+)\s*(?:m²|m2)", "high"),
        ("rooms", r"(?:Zimmer|Anzahl Zimmer)\s*[:\-]?\s*([\d.,]+)", "medium"),
        ("year_built", r"(?:Baujahr|Errichtungsjahr)\s*[:\-]?\s*((?:18|19|20)\d{2})", "high"),
        ("energy_hwb", r"(?:HWB(?:\s*Ref(?:,SK|,RK)?)?|Heizwärmebedarf)\s*[:\-]?\s*([\d.,]+)", "high"),
        ("energy_fgee", r"(?:fGEE|Gesamtenergieeffizienzfaktor)\s*[:\-]?\s*([\d.,]+)", "high"),
        ("price_eur", r"(?:Kaufpreis|Preis)\s*[:\-]?\s*(?:EUR|€)?\s*([\d. ,]+)", "medium"),
    ]
    for field, pattern, confidence in numeric_patterns:
        for match in _matches(pattern, normalized):
            if field in {"year_built"}:
                value: Any = _int_number(match.group(1))
            elif field == "price_eur":
                value = _int_number(match.group(1))
            else:
                value = _number(match.group(1))
            if value is None:
                continue
            if field == "energy_hwb" and not 1 <= float(value) <= 1000:
                continue
            if field == "energy_fgee" and not 0.1 <= float(value) <= 10:
                continue
            if field == "year_built" and not 1600 <= int(value) <= datetime.now().year + 2:
                continue
            items.append(_evidence(field, value, source_key, source_label, match.group(0), confidence))

    for field, pattern in [
        ("energy_class_hwb", r"(?:HWB[^\n]{0,30}(?:Klasse|Energieklasse)|Klasse\s+HWB)\s*[:\-]?\s*([A-G])\b"),
        ("energy_class_fgee", r"(?:fGEE[^\n]{0,30}(?:Klasse|Energieklasse)|Klasse\s+fGEE)\s*[:\-]?\s*([A-G])\b"),
    ]:
        for match in _matches(pattern, normalized):
            items.append(_evidence(field, match.group(1).upper(), source_key, source_label, match.group(0), "medium"))

    for match in _matches(r"(?:Heizung|Heizsystem|Wärmebereitstellung)\s*[:\-]?\s*([^\n;]{3,80})", normalized):
        value = _normalize_space(match.group(1))
        if not any(token in value.casefold() for token in ("hwb", "energieausweis", "heiztage")):
            items.append(_evidence("heating", value, source_key, source_label, match.group(0), "medium"))

    return items


def _subject_title(subjects: Iterable[str]) -> str:
    for subject in subjects:
        cleaned = re.sub(r"^(?:(?:fw|fwd|wg)\s*:\s*)+", "", subject or "", flags=re.IGNORECASE).strip()
        match = re.search(r"\bHaus\s+in\s+(.+)$", cleaned, flags=re.IGNORECASE)
        if match:
            return f"Haus in {_normalize_space(match.group(1))}"
        if cleaned and not cleaned.casefold().startswith("fotos "):
            return cleaned[:120]
    return "Manuell importiertes Objekt"


def _subject_location(subjects: Iterable[str]) -> str | None:
    for subject in subjects:
        cleaned = re.sub(r"^(?:(?:fw|fwd|wg)\s*:\s*)+", "", subject or "", flags=re.IGNORECASE).strip()
        match = re.search(r"(?:Haus|Haupthaus)\s+(?:in\s+)?(.+)$", cleaned, flags=re.IGNORECASE)
        if match:
            return _normalize_space(match.group(1))[:120]
    return None


def _field_value_key(field: str, value: Any) -> str:
    if field in {"price_eur", "living_area_m2", "plot_area_m2", "rooms", "year_built", "energy_hwb", "energy_fgee"}:
        parsed = _number(str(value))
        if parsed is not None:
            return f"{parsed:.8g}"
    return _normalize_compare(value)


def _pick_fields(evidence: list[dict[str, Any]], subjects: list[str]) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    fields: dict[str, Any] = {"title": _subject_title(subjects)}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in evidence:
        grouped.setdefault(str(item.get("field_name")), []).append(item)

    for field in FIELD_NAMES - {"title"}:
        candidates = grouped.get(field, [])
        if not candidates:
            continue
        candidates.sort(key=lambda item: CONFIDENCE_RANK.get(str(item.get("confidence")), 0), reverse=True)
        fields[field] = candidates[0].get("value")
        distinct: dict[str, Any] = {}
        for item in candidates:
            key = _field_value_key(field, item.get("value"))
            if key:
                distinct.setdefault(key, item.get("value"))
        distinct_items = list(distinct.items())
        if field == "location_text" and len(distinct_items) > 1:
            # Eine kürzere Adresse ohne PLZ/Ort ist keine echte Abweichung, wenn sie in der
            # vollständigeren Adresse enthalten ist.
            distinct_items = [
                item
                for item in distinct_items
                if not any(item[0] != other[0] and item[0] in other[0] for other in distinct_items)
            ]
        if len(distinct_items) > 1:
            shown = ", ".join(str(value) for _, value in distinct_items[:4])
            warnings.append(f"Widersprüchliche Werte für {field}: {shown}. Bitte vor dem Anlegen prüfen.")

    if not fields.get("location_text"):
        fields["location_text"] = _subject_location(subjects)
    fields["address_status"] = "review" if any("location_text" in warning for warning in warnings) else ("parsed" if fields.get("location_text") else "unknown")
    return fields, warnings


def _save_artifact(
    session_dir: Path,
    content: bytes,
    filename: str,
    mime_type: str,
    source_key: str,
    source_label: str,
    *,
    original_email: bool = False,
) -> dict[str, Any] | None:
    if not content:
        return None
    extension = Path(filename).suffix.casefold()
    if extension not in ALLOWED_EXTENSIONS:
        return None
    artifact_dir = session_dir / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    content_hash = _sha256(content)
    existing_manifest = session_dir / "artifact_hashes.json"
    hashes: dict[str, str] = {}
    if existing_manifest.exists():
        try:
            hashes = json.loads(existing_manifest.read_text(encoding="utf-8"))
        except Exception:
            hashes = {}
    if content_hash in hashes:
        return None
    target = _unique_target(artifact_dir, filename)
    target.write_bytes(content)
    hashes[content_hash] = target.name
    existing_manifest.write_text(json.dumps(hashes, ensure_ascii=False, indent=2), encoding="utf-8")

    text = ""
    pages = 0
    warnings: list[str] = []
    width: int | None = None
    height: int | None = None
    if extension == ".pdf":
        text, pages, warnings = _extract_pdf_text(target)
    elif extension in IMAGE_EXTENSIONS:
        width, height = _image_dimensions(content)
        if _looks_like_signature_image(filename, width, height, len(content)):
            warnings.append("Kleines Inline-Bild; als mögliches Logo/Signaturbild markiert und nicht als Hauptfoto priorisiert.")
    classification = _classify_document(filename, text)
    return {
        "filename": target.name,
        "original_filename": _safe_filename(filename),
        "path": str(target.relative_to(session_dir)),
        "mime_type": mime_type or "application/octet-stream",
        "size": len(content),
        "content_hash": content_hash,
        "source_key": source_key,
        "source_label": source_label,
        "classification": classification,
        "text": text,
        "pages": pages,
        "width": width,
        "height": height,
        "warnings": warnings,
        "is_original_email": original_email,
    }


def _walk_message(
    message: Message,
    session_dir: Path,
    fallback_name: str,
    source_key: str,
    source_label: str,
    artifacts: list[dict[str, Any]],
    bodies: list[dict[str, str]],
    sources: dict[str, dict[str, Any]],
) -> None:
    current_source = sources.setdefault(
        source_key,
        {
            "key": source_key,
            "label": source_label,
            "subject": "",
            "sender": "",
            "date": "",
            "message_id": "",
        },
    )
    for field, header_name in (("subject", "Subject"), ("sender", "From"), ("date", "Date"), ("message_id", "Message-ID")):
        header_value = _header(message, header_name)
        if field == "message_id":
            header_value = header_value.strip("<>")
        if header_value and not current_source.get(field):
            current_source[field] = header_value
    if message.is_multipart():
        for part in message.iter_parts():
            if part.get_content_type() == "message/rfc822":
                payload = part.get_payload()
                nested_messages = payload if isinstance(payload, list) else [payload]
                for nested in nested_messages:
                    if isinstance(nested, Message):
                        raw = nested.as_bytes(policy=policy.default)
                        nested_hash = _sha256(raw)
                        nested_key = _message_key(nested, nested_hash)
                        nested_label = _email_source_label(nested, fallback_name)
                        _walk_message(nested, session_dir, fallback_name, nested_key, nested_label, artifacts, bodies, sources)
                continue
            if part.is_multipart():
                _walk_message(part, session_dir, fallback_name, source_key, source_label, artifacts, bodies, sources)
                continue
            filename = part.get_filename()
            disposition = part.get_content_disposition()
            content_type = part.get_content_type()
            if content_type in {"text/plain", "text/html"} and not filename:
                try:
                    content = part.get_content()
                except Exception:
                    content = ""
                body_text = _html_to_text(str(content)) if content_type == "text/html" else str(content)
                if body_text.strip():
                    bodies.append({"source_key": source_key, "source_label": source_label, "text": body_text[:300_000]})
                continue
            if filename or disposition in {"attachment", "inline"}:
                try:
                    content = part.get_payload(decode=True) or b""
                except Exception:
                    content = b""
                if not filename:
                    guessed = ".jpg" if content_type == "image/jpeg" else ".png" if content_type == "image/png" else ".bin"
                    filename = f"inline_{uuid.uuid4().hex[:8]}{guessed}"
                artifact = _save_artifact(session_dir, content, filename, content_type, source_key, source_label)
                if artifact:
                    artifacts.append(artifact)
        return

    content_type = message.get_content_type()
    if content_type in {"text/plain", "text/html"}:
        try:
            content = message.get_content()
        except Exception:
            content = ""
        body_text = _html_to_text(str(content)) if content_type == "text/html" else str(content)
        if body_text.strip():
            bodies.append({"source_key": source_key, "source_label": source_label, "text": body_text[:300_000]})


def _process_saved_inputs(session_dir: Path, inputs: list[SavedInput]) -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []
    bodies: list[dict[str, str]] = []
    sources: dict[str, dict[str, Any]] = {}
    subjects: list[str] = []
    warnings: list[str] = []

    for item in inputs:
        content = item.path.read_bytes()
        extension = item.path.suffix.casefold()
        if extension == ".eml":
            try:
                message = BytesParser(policy=policy.default).parsebytes(content)
            except Exception as exc:
                warnings.append(f"{item.filename}: E-Mail konnte nicht gelesen werden: {str(exc)[:180]}")
                continue
            source_key = _message_key(message, _sha256(content))
            source_label = _email_source_label(message, item.filename)
            original = _save_artifact(session_dir, content, item.filename, "message/rfc822", source_key, source_label, original_email=True)
            if original:
                artifacts.append(original)
            subject = _header(message, "Subject")
            if subject:
                subjects.append(subject)
            _walk_message(message, session_dir, item.filename, source_key, source_label, artifacts, bodies, sources)
        else:
            sources[item.source_key] = {"key": item.source_key, "label": item.source_label, "subject": "", "sender": "", "date": "", "message_id": ""}
            artifact = _save_artifact(session_dir, content, item.filename, item.mime_type, item.source_key, item.source_label)
            if artifact:
                artifacts.append(artifact)

    evidence: list[dict[str, Any]] = []
    for body in bodies:
        evidence.extend(_extract_evidence(body["text"], "E-Mail-Text", body["source_key"], body["source_label"]))
    for artifact in artifacts:
        if artifact.get("text"):
            evidence.extend(
                _extract_evidence(
                    str(artifact.get("text") or ""),
                    str(artifact.get("classification") or ""),
                    str(artifact.get("source_key") or ""),
                    f"{artifact.get('source_label')} · {artifact.get('original_filename')}",
                )
            )
        warnings.extend(f"{artifact.get('original_filename')}: {warning}" for warning in artifact.get("warnings") or [])

    fields, conflict_warnings = _pick_fields(evidence, subjects)
    warnings.extend(conflict_warnings)
    if not artifacts:
        warnings.append("Keine unterstützten Anhänge oder Bilder gefunden.")
    if not any(artifact.get("classification") == "Objektfoto" and not artifact.get("warnings") for artifact in artifacts):
        warnings.append("Keine eindeutig geeigneten Objektfotos erkannt.")

    return {
        "version": 1,
        "created_at": now_iso(),
        "subjects": subjects,
        "sources": list(sources.values()),
        "artifacts": artifacts,
        "evidence": evidence,
        "fields": fields,
        "warnings": list(dict.fromkeys(warnings)),
    }


def _cleanup_sessions() -> None:
    IMPORT_ROOT.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - SESSION_MAX_AGE_SECONDS
    for path in IMPORT_ROOT.iterdir():
        try:
            if path.is_dir() and path.stat().st_mtime < cutoff:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            continue


def _load_manifest(session_id: str) -> tuple[Path, dict[str, Any]]:
    if not re.fullmatch(r"[a-f0-9]{16}", session_id or ""):
        raise HTTPException(status_code=400, detail="Ungültige Importsitzung")
    session_dir = IMPORT_ROOT / session_id
    manifest_path = session_dir / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Importsitzung nicht gefunden oder abgelaufen")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Importvorschau ist beschädigt") from exc
    return session_dir, manifest


def _size_label(value: int) -> str:
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):.1f} MB".replace(".", ",")
    return f"{max(1, round(value / 1024))} KB"


def _input_value(fields: dict[str, Any], key: str) -> str:
    value = fields.get(key)
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).replace(".", ",") if isinstance(value, float) else str(value)


def _preview_page(session_id: str, manifest: dict[str, Any]) -> HTMLResponse:
    fields = manifest.get("fields") or {}
    warnings = manifest.get("warnings") or []
    artifacts = manifest.get("artifacts") or []
    evidence = manifest.get("evidence") or []
    warning_html = "".join(f"<li>{esc(item)}</li>" for item in warnings) or "<li>Keine Konflikte erkannt.</li>"
    artifact_rows = "".join(
        f"<tr><td><strong>{esc(item.get('original_filename'))}</strong><br><span class='muted'>{esc(_size_label(int(item.get('size') or 0)))}</span></td><td>{esc(item.get('classification'))}</td><td>{esc(item.get('source_label'))}</td><td>{'Text erkannt' if item.get('text') else 'Bild/Scan'}</td></tr>"
        for item in artifacts
    )
    evidence_rows = "".join(
        f"<tr><td>{esc(item.get('field_name'))}</td><td>{esc(item.get('value'))}</td><td>{esc(item.get('confidence'))}</td><td>{esc(item.get('source_label'))}</td></tr>"
        for item in evidence[:80]
    )
    body = f"""
    <div class="page-heading"><div><h1>Hausakt aus E-Mails anlegen</h1><p>Daten prüfen, Konflikte korrigieren und erst danach speichern.</p></div><a class="button ghost" href="../../import">{modern_ui.icon('back')} Zurück</a></div>
    <div class="card notice warning"><strong>Prüfung erforderlich</strong><ul>{warning_html}</ul></div>
    <form method="post" action="confirm" data-loading="Hausakte, Dokumente und Bilder werden angelegt …">
      <input type="hidden" name="session_id" value="{esc(session_id)}">
      <div class="card section">
        <h2>Objektdaten</h2>
        <label>Titel</label><input name="title" required value="{esc(_input_value(fields, 'title'))}">
        <label>Adresse / Lage</label><input name="location_text" value="{esc(_input_value(fields, 'location_text'))}" placeholder="z. B. Eichegg 51a, 8542 Wies">
        <div class="grid">
          <div><label>Kaufpreis €</label><input name="price_eur" inputmode="decimal" value="{esc(_input_value(fields, 'price_eur'))}"></div>
          <div><label>Wohn-/Bezugsfläche m²</label><input name="living_area_m2" inputmode="decimal" value="{esc(_input_value(fields, 'living_area_m2'))}"></div>
          <div><label>Grundstück m²</label><input name="plot_area_m2" inputmode="decimal" value="{esc(_input_value(fields, 'plot_area_m2'))}"></div>
          <div><label>Zimmer</label><input name="rooms" inputmode="decimal" value="{esc(_input_value(fields, 'rooms'))}"></div>
          <div><label>Baujahr</label><input name="year_built" inputmode="numeric" value="{esc(_input_value(fields, 'year_built'))}"></div>
          <div><label>Heizung</label><input name="heating" value="{esc(_input_value(fields, 'heating'))}"></div>
          <div><label>HWB</label><input name="energy_hwb" inputmode="decimal" value="{esc(_input_value(fields, 'energy_hwb'))}"></div>
          <div><label>fGEE</label><input name="energy_fgee" inputmode="decimal" value="{esc(_input_value(fields, 'energy_fgee'))}"></div>
          <div><label>HWB-Klasse</label><input name="energy_class_hwb" maxlength="2" value="{esc(_input_value(fields, 'energy_class_hwb'))}"></div>
          <div><label>fGEE-Klasse</label><input name="energy_class_fgee" maxlength="2" value="{esc(_input_value(fields, 'energy_class_fgee'))}"></div>
        </div>
        <label>Notizen</label><textarea name="notes" rows="4" placeholder="Ergänzungen zum Objekt"></textarea>
        <label style="display:flex;align-items:center;gap:10px"><input style="width:auto;margin:0" type="checkbox" name="start_analysis" value="1" checked> Dokumente und Bilder danach automatisch durch die bestehende KI-Pipeline prüfen</label>
        <div class="action-row section"><button type="submit">Hausakt als Entwurf anlegen</button></div>
      </div>
    </form>
    <div class="card section"><h2>Dokumente und Bilder</h2><table><tr><th>Datei</th><th>Erkannt als</th><th>Quelle</th><th>Lesbarkeit</th></tr>{artifact_rows}</table></div>
    <div class="card section"><details><summary><strong>Erkannte Feldherkunft</strong></summary><table><tr><th>Feld</th><th>Wert</th><th>Sicherheit</th><th>Quelle</th></tr>{evidence_rows or '<tr><td colspan="4" class="muted">Noch keine maschinenlesbaren Felder erkannt.</td></tr>'}</table></details></div>
    <form method="post" action="cancel" data-no-loading="true"><input type="hidden" name="session_id" value="{esc(session_id)}"><button class="secondary" type="submit">Import verwerfen</button></form>
    """
    return modern_ui.modern_layout("E-Mail-Import prüfen", body, home_href="../../")


def _form_float(value: str | None) -> float | None:
    return _number(value)


def _form_int(value: str | None) -> int | None:
    return _int_number(value)


def _copy_artifacts_to_house(session_dir: Path, manifest: dict[str, Any], house_id: str, source_ids: dict[str, str]) -> dict[str, int]:
    target_root = project_dir(house_id)
    (target_root / "emails").mkdir(parents=True, exist_ok=True)
    (target_root / "documents").mkdir(parents=True, exist_ok=True)
    counts = {"images": 0, "pdfs": 0, "emails": 0, "skipped": 0}
    manifest_copy = json.loads(json.dumps(manifest, ensure_ascii=False))
    for artifact in manifest_copy.get("artifacts") or []:
        artifact.pop("text", None)
    (target_root / "html" / "manual_mail_import.json").write_text(json.dumps(manifest_copy, ensure_ascii=False, indent=2), encoding="utf-8")

    for artifact in manifest.get("artifacts") or []:
        source_path = session_dir / str(artifact.get("path") or "")
        try:
            source_path.resolve().relative_to(session_dir.resolve())
        except ValueError:
            continue
        if not source_path.exists():
            continue
        extension = source_path.suffix.casefold()
        if extension in IMAGE_EXTENSIONS:
            kind, subdir, counter = "image", "images", "images"
        elif extension == ".pdf":
            kind, subdir, counter = "pdf", "pdfs", "pdfs"
        elif extension == ".eml":
            kind, subdir, counter = "email", "emails", "emails"
        else:
            kind, subdir, counter = "document", "documents", "skipped"
        content = source_path.read_bytes()
        content_hash = _sha256(content)
        duplicate = find_media_by_hash(house_id, kind, content_hash)
        if duplicate:
            counts["skipped"] += 1
            continue
        target = _unique_target(target_root / subdir, str(artifact.get("original_filename") or source_path.name))
        shutil.copy2(source_path, target)
        if kind == "image":
            meta = main.image_meta(content)
        else:
            meta = main.binary_meta(content)
        add_media(
            house_id,
            {
                **meta,
                "source_id": source_ids.get(str(artifact.get("source_key") or "")),
                "kind": kind,
                "original_url": f"mail-import://{artifact.get('content_hash')}/{artifact.get('original_filename')}",
                "local_path": str(target),
                "mime_type": artifact.get("mime_type"),
                "download_status": "downloaded",
            },
        )
        counts[counter] += 1
    return counts


def register_mail_import(app: FastAPI) -> None:
    _cleanup_sessions()
    _remove_route(app, "/import", "GET")

    @app.get("/import", response_class=HTMLResponse)
    def import_choice() -> HTMLResponse:
        body = f"""
        <div class="page-heading"><div><h1>Hausakt anlegen</h1><p>Inserat importieren oder E-Mails, PDFs und Bilder gemeinsam auswerten.</p></div><a class="button ghost" href="./">{modern_ui.icon('back')} Zurück</a></div>
        <div class="grid">
          <div class="card">
            <h2>Inserat-Link</h2><p class="muted">Portal-Link einlesen, Bilder laden und bestehende Analyse starten.</p>
            <form method="post" action="import" data-loading="Inserat wird importiert und Bilder werden geladen …"><label>Direktlink</label><input name="url" type="url" required placeholder="https://www.willhaben.at/iad/immobilien/d/…"><button type="submit">Inserat importieren</button></form>
          </div>
          <div class="card">
            <h2>E-Mails, PDFs und Bilder</h2><p class="muted">Mehrere heruntergeladene Gmail-Nachrichten (.eml) gemeinsam hochladen. PDF-Anhänge und Inline-Fotos werden automatisch übernommen. Direkte PDFs/Bilder sind ebenfalls möglich.</p>
            <form method="post" action="import/mail/preview" enctype="multipart/form-data" data-loading="E-Mails, PDFs und Bilder werden geprüft …"><label>Dateien auswählen</label><input type="file" name="files" multiple required accept=".eml,.pdf,.jpg,.jpeg,.png,.webp,.heic,.heif,message/rfc822,application/pdf,image/*"><button type="submit">Dateien prüfen und Daten extrahieren</button></form>
            <p class="muted">In Gmail: Nachricht öffnen → ⋮ → „Nachricht herunterladen“. Beide .eml-Dateien können gleichzeitig gewählt werden.</p>
          </div>
        </div>
        <div class="card section notice"><strong>Sicherer Ablauf:</strong> HausCheck legt noch keine Hausakte an. Zuerst erscheint eine Vorschau mit Feldherkunft, Dokumentklassifizierung und möglichen Widersprüchen.</div>
        """
        return modern_ui.modern_layout("Hausakt anlegen", body, home_href="./")

    @app.post("/import/mail/preview", response_class=HTMLResponse)
    async def preview_mail_import(files: list[UploadFile] = File(...)) -> HTMLResponse:
        _cleanup_sessions()
        if not files or len(files) > MAX_UPLOADS:
            raise HTTPException(status_code=400, detail=f"Bitte 1 bis {MAX_UPLOADS} Dateien auswählen")
        session_id = uuid.uuid4().hex[:16]
        session_dir = IMPORT_ROOT / session_id
        upload_dir = session_dir / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=False)
        saved: list[SavedInput] = []
        total = 0
        try:
            for upload in files:
                filename = _safe_filename(upload.filename, "upload.bin")
                extension = Path(filename).suffix.casefold()
                if extension not in ALLOWED_EXTENSIONS:
                    raise HTTPException(status_code=400, detail=f"Nicht unterstützte Datei: {filename}")
                content = await upload.read(MAX_FILE_BYTES + 1)
                if len(content) > MAX_FILE_BYTES:
                    raise HTTPException(status_code=413, detail=f"Datei zu groß: {filename} (max. 30 MB)")
                total += len(content)
                if total > MAX_TOTAL_BYTES:
                    raise HTTPException(status_code=413, detail="Gesamtupload ist zu groß (max. 140 MB)")
                if extension == ".pdf" and not content.startswith(b"%PDF-"):
                    raise HTTPException(status_code=400, detail=f"Ungültige PDF-Datei: {filename}")
                target = _unique_target(upload_dir, filename)
                target.write_bytes(content)
                source_key = f"direct:{_sha256(content)[:20]}"
                saved.append(SavedInput(filename=target.name, path=target, mime_type=upload.content_type or "application/octet-stream", source_key=source_key, source_label="Direkt hochgeladen"))
            manifest = _process_saved_inputs(session_dir, saved)
            manifest["session_id"] = session_id
            manifest["upload_count"] = len(files)
            manifest["total_bytes"] = total
            (session_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            return _preview_page(session_id, manifest)
        except Exception:
            shutil.rmtree(session_dir, ignore_errors=True)
            raise

    @app.post("/import/mail/confirm")
    async def confirm_mail_import(
        session_id: str = Form(...),
        title: str = Form(...),
        location_text: str | None = Form(None),
        price_eur: str | None = Form(None),
        living_area_m2: str | None = Form(None),
        plot_area_m2: str | None = Form(None),
        rooms: str | None = Form(None),
        year_built: str | None = Form(None),
        heating: str | None = Form(None),
        energy_hwb: str | None = Form(None),
        energy_fgee: str | None = Form(None),
        energy_class_hwb: str | None = Form(None),
        energy_class_fgee: str | None = Form(None),
        notes: str | None = Form(None),
        start_analysis: int = Form(0),
    ) -> RedirectResponse:
        session_dir, manifest = _load_manifest(session_id)
        clean_title = _normalize_space(title)
        if not clean_title:
            raise HTTPException(status_code=400, detail="Titel fehlt")
        house = create_house(
            {
                "title": clean_title[:180],
                "status": "new",
                "location_text": _normalize_space(location_text) or None,
                "address_status": str((manifest.get("fields") or {}).get("address_status") or "review"),
                "price_eur": _form_int(price_eur),
                "living_area_m2": _form_float(living_area_m2),
                "plot_area_m2": _form_float(plot_area_m2),
                "rooms": _form_float(rooms),
                "year_built": _form_int(year_built),
                "heating": _normalize_space(heating) or None,
                "energy_hwb": _form_float(energy_hwb),
                "energy_fgee": _form_float(energy_fgee),
                "energy_class_hwb": _normalize_space(energy_class_hwb).upper() or None,
                "energy_class_fgee": _normalize_space(energy_class_fgee).upper() or None,
                "notes": _normalize_space(notes) or None,
            }
        )
        house_id = str(house["id"])
        source_ids: dict[str, str] = {}
        warnings = manifest.get("warnings") or []
        for source in manifest.get("sources") or []:
            key = str(source.get("key") or f"manual:{uuid.uuid4().hex[:8]}")
            label = str(source.get("label") or "E-Mail-/Dokumentenimport")
            source_row = create_source(
                house_id,
                {
                    "source_name": label[:180],
                    "source_url": f"mail-import://{session_id}/{hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]}",
                    "external_id": source.get("message_id") or None,
                    "description": " · ".join(part for part in [source.get("subject"), source.get("sender"), source.get("date")] if part),
                    "parser_status": "partial" if warnings else "success",
                    "parser_warnings": warnings,
                },
            )
            source_ids[key] = str(source_row["id"])
        if not source_ids:
            source_row = create_source(
                house_id,
                {
                    "source_name": "Manueller Dokumentenimport",
                    "source_url": f"mail-import://{session_id}/direct",
                    "parser_status": "partial" if warnings else "success",
                    "parser_warnings": warnings,
                },
            )
            source_ids["direct"] = str(source_row["id"])

        evidence_by_source: dict[str, list[dict[str, Any]]] = {}
        for item in manifest.get("evidence") or []:
            source_key = str(item.get("source_key") or "direct")
            evidence_by_source.setdefault(source_key, []).append(item)
        for source_key, items in evidence_by_source.items():
            add_evidence(house_id, source_ids.get(source_key) or next(iter(source_ids.values())), items)

        counts = _copy_artifacts_to_house(session_dir, manifest, house_id, source_ids)
        summary = f"Manueller E-Mail-Import: {counts['images']} Bilder, {counts['pdfs']} PDFs, {counts['emails']} Original-E-Mails übernommen"
        if warnings:
            summary += f" · {len(warnings)} Prüfhinweis(e)"
        set_pipeline_stage(house_id, "media_ready", "ok", summary)
        if start_analysis:
            set_pipeline_stage(house_id, "exporting", "running", "E-Mail-Import abgeschlossen. KI-Analyse wird bereitgestellt.")
            try:
                started = bool(await auto_export_house_to_github(house_id))
                if not started:
                    set_pipeline_stage(house_id, "media_ready", "ok", summary + " · KI-Export ist derzeit nicht konfiguriert")
            except Exception as exc:
                set_pipeline_stage(house_id, "error", "error", "Hausakte wurde angelegt, KI-Export ist fehlgeschlagen.", error=str(exc)[:800])
        shutil.rmtree(session_dir, ignore_errors=True)
        return RedirectResponse(f"../../houses/{house_id}", status_code=303)

    @app.post("/import/mail/cancel")
    def cancel_mail_import(session_id: str = Form(...)) -> RedirectResponse:
        session_dir, _ = _load_manifest(session_id)
        shutil.rmtree(session_dir, ignore_errors=True)
        return RedirectResponse("../../import", status_code=303)
