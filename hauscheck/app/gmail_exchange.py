from __future__ import annotations

import asyncio
import imaplib
import json
import mimetypes
import os
import re
import smtplib
import zipfile
from dataclasses import dataclass
from email import policy
from email.headerregistry import Address
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse

from app.analysis_package import create_analysis_zip, extract_analysis_json_from_upload, save_analysis
from app.storage import get_house


OPTIONS_PATH = Path("/data/options.json")
_export_subject_re = re.compile(r"HAUSCHECK_EXPORT\s+([A-Za-z0-9_-]+)", re.IGNORECASE)
_result_subject_re = re.compile(r"HAUSCHECK_RESULT\s+([A-Za-z0-9_-]+)", re.IGNORECASE)
_gmail_import_task: asyncio.Task | None = None


@dataclass
class GmailExchangeSettings:
    enabled: bool = False
    auto_send_on_import: bool = True
    auto_import_results: bool = True
    import_interval_minutes: int = 5
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    username: str = ""
    app_password: str = ""
    to: str = ""
    from_name: str = "HausCheck Pro"
    mark_results_seen: bool = True
    inline_package: bool = True
    attach_images: bool = True
    image_limit: int = 8
    send_zip_attachment: bool = False

    @property
    def send_ready(self) -> bool:
        return bool(self.enabled and self.auto_send_on_import and self.username and self.app_password and self.to)

    @property
    def import_ready(self) -> bool:
        return bool(self.enabled and self.auto_import_results and self.username and self.app_password)


def _load_options() -> dict[str, Any]:
    if not OPTIONS_PATH.exists():
        return {}
    try:
        return json.loads(OPTIONS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if value is True:
        return True
    if value is False:
        return False
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "ja"}:
        return True
    if text in {"0", "false", "no", "off", "nein"}:
        return False
    return default


def _int_option(value: Any, default: int, min_value: int = 1, max_value: int = 1440) -> int:
    try:
        result = int(float(str(value)))
    except Exception:
        result = default
    return max(min_value, min(result, max_value))


def load_gmail_settings() -> GmailExchangeSettings:
    data = _load_options()

    def env_or_option(name: str, default: Any = "") -> Any:
        env = os.environ.get(f"HAUSCHECK_{name.upper()}")
        if env is not None:
            return env
        return data.get(name, default)

    username = str(env_or_option("gmail_username", "") or "").strip()
    to = str(env_or_option("gmail_to", "") or "").strip() or username
    return GmailExchangeSettings(
        enabled=_truthy(env_or_option("gmail_exchange_enabled", False), False),
        auto_send_on_import=_truthy(env_or_option("gmail_auto_send_on_import", True), True),
        auto_import_results=_truthy(env_or_option("gmail_auto_import_results", True), True),
        import_interval_minutes=_int_option(env_or_option("gmail_import_interval_minutes", 5), 5),
        smtp_host=str(env_or_option("gmail_smtp_host", "smtp.gmail.com") or "smtp.gmail.com").strip(),
        smtp_port=_int_option(env_or_option("gmail_smtp_port", 587), 587, 1, 65535),
        imap_host=str(env_or_option("gmail_imap_host", "imap.gmail.com") or "imap.gmail.com").strip(),
        imap_port=_int_option(env_or_option("gmail_imap_port", 993), 993, 1, 65535),
        username=username,
        app_password=str(env_or_option("gmail_app_password", "") or "").strip(),
        to=to,
        from_name=str(env_or_option("gmail_from_name", "HausCheck Pro") or "HausCheck Pro").strip(),
        mark_results_seen=_truthy(env_or_option("gmail_mark_results_seen", True), True),
        inline_package=_truthy(env_or_option("gmail_inline_package", True), True),
        attach_images=_truthy(env_or_option("gmail_attach_images", True), True),
        image_limit=_int_option(env_or_option("gmail_image_limit", 8), 8, 0, 20),
        send_zip_attachment=_truthy(env_or_option("gmail_send_zip_attachment", False), False),
    )


def _plain_text_parts(msg: EmailMessage) -> list[str]:
    parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get_content_type() == "text/plain":
                try:
                    content = part.get_content()
                    if isinstance(content, str):
                        parts.append(content)
                except Exception:
                    pass
    else:
        if msg.get_content_type() == "text/plain":
            try:
                content = msg.get_content()
                if isinstance(content, str):
                    parts.append(content)
            except Exception:
                pass
    return parts


def _json_from_text(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    candidates: list[str] = []
    if stripped.startswith("{") and stripped.endswith("}"):
        candidates.append(stripped)
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    candidates.extend(fenced)
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        candidates.append(text[first:last + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return None


def _extract_analysis_from_message(msg: EmailMessage) -> dict[str, Any] | None:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            filename = part.get_filename() or ""
            content_type = part.get_content_type() or ""
            if filename.lower().endswith(".json") or content_type in {"application/json", "text/json"}:
                payload = part.get_payload(decode=True) or b""
                if payload:
                    return extract_analysis_json_from_upload(filename or "hauscheck_analysis.json", payload)
    for text in _plain_text_parts(msg):
        data = _json_from_text(text)
        if data:
            return data
    return None


def _zip_text(zf: zipfile.ZipFile, name: str, max_chars: int = 120_000) -> str:
    try:
        with zf.open(name) as handle:
            text = handle.read().decode("utf-8", errors="replace")
    except Exception:
        return ""
    if len(text) > max_chars:
        return text[:max_chars] + "\n\n[GEKÜRZT]"
    return text


def _mail_package_body(house_id: str, zip_path: Path) -> str:
    parts: list[str] = [
        "HAUSCHECK_MAIL_PACKAGE_V2",
        f"HOUSE_ID: {house_id}",
        "",
        "AUFGABE:",
        "Analysiere dieses HausCheck-Paket anhand der unten eingefügten Daten.",
        "Antworte mit einer neuen E-Mail mit exakt diesem Betreff:",
        f"HAUSCHECK_RESULT {house_id}",
        "",
        "Antwortformat:",
        "Nur reines JSON als Mailbody. Kein Markdown. Kein Codeblock. Kein zusätzlicher Text.",
        "Die JSON-Struktur muss zur import_schema.json passen und house_id exakt übernehmen.",
        "",
        "BILDER:",
        "Wenn Bildanhänge vorhanden und lesbar sind, beziehe sie in die Bewertung ein.",
        "Wenn Bildanhänge nicht lesbar sind, analysiere nur die Text-/Inseratsdaten und nenne das in limitations.",
        "",
    ]
    file_names = [
        "README_PROMPT.md",
        "listing.json",
        "evidence.json",
        "current_score.json",
        "import_schema.json",
        "image_manifest.json",
        "original/source_urls.txt",
    ]
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for name in file_names:
                text = _zip_text(zf, name)
                if not text:
                    continue
                parts.append(f"\n--- BEGIN {name} ---\n{text}\n--- END {name} ---\n")
    except Exception as exc:
        parts.append(f"\nWARNUNG: ZIP-Inhalt konnte nicht vollständig gelesen werden: {exc}\n")
    return "\n".join(parts)


def _image_entries(zip_path: Path, limit: int) -> list[tuple[str, bytes, str]]:
    if limit <= 0:
        return []
    items: list[tuple[str, bytes, str]] = []
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = [name for name in zf.namelist() if name.lower().startswith("images/") and not name.endswith("/")]
            names.sort()
            for idx, name in enumerate(names[:limit], start=1):
                data = zf.read(name)
                suffix = Path(name).suffix.lower() or ".jpg"
                filename = f"hauscheck_image_{idx:02d}{suffix}"
                content_type = mimetypes.guess_type(filename)[0] or "image/jpeg"
                items.append((filename, data, content_type))
    except Exception as exc:
        print(f"HausCheck Gmail Bildanhänge konnten nicht vorbereitet werden: {exc}", flush=True)
    return items


def _build_export_mail(settings: GmailExchangeSettings, house_id: str, zip_path: Path) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"HAUSCHECK_EXPORT {house_id}"
    msg["From"] = Address(display_name=settings.from_name or "HausCheck Pro", addr_spec=settings.username)
    msg["To"] = settings.to

    if settings.inline_package:
        msg.set_content(_mail_package_body(house_id, zip_path))
    else:
        msg.set_content(
            "HausCheck Analysepaket.\n\n"
            f"house_id: {house_id}\n\n"
            "Bitte anhand der Anhänge analysieren.\n"
            f"Antwort bitte mit Betreff: HAUSCHECK_RESULT {house_id}\n"
            "Antwortbody bitte als reines JSON ohne Markdown.\n"
        )

    if settings.attach_images:
        for filename, data, content_type in _image_entries(zip_path, settings.image_limit):
            maintype, subtype = content_type.split("/", 1)
            msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)

    if settings.send_zip_attachment:
        msg.add_attachment(zip_path.read_bytes(), maintype="application", subtype="zip", filename=zip_path.name)

    return msg


def _send_mail_sync(settings: GmailExchangeSettings, house_id: str, zip_path: Path) -> None:
    msg = _build_export_mail(settings, house_id, zip_path)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=90) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(settings.username, settings.app_password)
        smtp.send_message(msg)


async def send_analysis_zip_via_gmail(house_id: str) -> bool:
    settings = load_gmail_settings()
    if not settings.send_ready:
        return False
    if not get_house(house_id):
        print(f"HausCheck Gmail Exchange übersprungen: Hausakte nicht gefunden: {house_id}", flush=True)
        return False
    try:
        zip_path = create_analysis_zip(house_id)
        await asyncio.to_thread(_send_mail_sync, settings, house_id, zip_path)
        print(f"HausCheck Gmail Export OK: HAUSCHECK_EXPORT {house_id} an {settings.to}", flush=True)
        return True
    except Exception as exc:
        print(f"HausCheck Gmail Export fehlgeschlagen für {house_id}: {exc}", flush=True)
        return False


def _imap_search_result_messages(imap: imaplib.IMAP4_SSL) -> list[bytes]:
    queries = [
        '(UNSEEN SUBJECT "HAUSCHECK_RESULT")',
        '(UNSEEN SUBJECT "HAUSCHECK")',
    ]
    ids: list[bytes] = []
    seen: set[bytes] = set()
    for query in queries:
        status, data = imap.search(None, query)
        if status != "OK" or not data:
            continue
        for msg_id in (data[0] or b"").split():
            if msg_id not in seen:
                ids.append(msg_id)
                seen.add(msg_id)
    return ids


def _import_results_sync(settings: GmailExchangeSettings) -> dict[str, Any]:
    imported: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    checked = 0

    with imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port) as imap:
        imap.login(settings.username, settings.app_password)
        imap.select("INBOX")
        for msg_id in _imap_search_result_messages(imap):
            checked += 1
            try:
                status, data = imap.fetch(msg_id, "(RFC822)")
                if status != "OK" or not data or not data[0]:
                    raise ValueError("E-Mail konnte nicht gelesen werden")
                raw = data[0][1]
                msg = BytesParser(policy=policy.default).parsebytes(raw)
                subject = str(msg.get("Subject") or "")
                if "HAUSCHECK_RESULT" not in subject.upper():
                    continue
                subject_house_id = ""
                match = _result_subject_re.search(subject)
                if match:
                    subject_house_id = match.group(1).strip()

                analysis = _extract_analysis_from_message(msg)
                if not analysis:
                    raise ValueError("Keine hauscheck_analysis.json und kein JSON im Text gefunden")
                house_id = str(analysis.get("house_id") or subject_house_id or "").strip()
                if not house_id:
                    raise ValueError("house_id fehlt")
                if subject_house_id and house_id != subject_house_id:
                    raise ValueError(f"house_id im JSON ({house_id}) passt nicht zum Betreff ({subject_house_id})")
                if not get_house(house_id):
                    raise ValueError(f"Hausakte {house_id} nicht gefunden")

                save_analysis(house_id, analysis)
                imported.append({"house_id": house_id, "subject": subject})
                if settings.mark_results_seen:
                    imap.store(msg_id, "+FLAGS", "\\Seen")
            except Exception as exc:
                errors.append({"id": msg_id.decode(errors="ignore"), "error": str(exc)[:500]})

    return {"checked": checked, "imported": imported, "errors": errors}


async def import_gmail_results() -> dict[str, Any]:
    settings = load_gmail_settings()
    if not settings.import_ready:
        return {"checked": 0, "imported": [], "errors": [], "disabled": True}
    return await asyncio.to_thread(_import_results_sync, settings)


async def _gmail_auto_import_loop() -> None:
    await asyncio.sleep(30)
    while True:
        settings = load_gmail_settings()
        sleep_seconds = max(60, settings.import_interval_minutes * 60)
        try:
            if settings.import_ready:
                result = await import_gmail_results()
                imported = result.get("imported") or []
                errors = result.get("errors") or []
                checked = result.get("checked") or 0
                if imported or errors:
                    print(
                        f"HausCheck Gmail Auto-Import: geprüft={checked}, importiert={len(imported)}, fehler={len(errors)}",
                        flush=True,
                    )
                    for item in imported[:10]:
                        print(f"HausCheck Gmail Auto-Import OK: {item}", flush=True)
                    for item in errors[:10]:
                        print(f"HausCheck Gmail Auto-Import Fehler: {item}", flush=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"HausCheck Gmail Auto-Import fehlgeschlagen: {exc}", flush=True)
        await asyncio.sleep(sleep_seconds)


def register_gmail_exchange(app: FastAPI) -> None:
    @app.on_event("startup")
    async def start_gmail_exchange() -> None:
        global _gmail_import_task
        if _gmail_import_task is None or _gmail_import_task.done():
            _gmail_import_task = asyncio.create_task(_gmail_auto_import_loop())
            print("HausCheck Gmail Exchange gestartet", flush=True)

    @app.on_event("shutdown")
    async def stop_gmail_exchange() -> None:
        global _gmail_import_task
        if _gmail_import_task and not _gmail_import_task.done():
            _gmail_import_task.cancel()
        _gmail_import_task = None

    @app.post("/gmail/import-results")
    async def gmail_import_results_route() -> dict[str, Any]:
        return await import_gmail_results()

    @app.post("/houses/{house_id}/gmail-send")
    async def gmail_send_house_route(house_id: str) -> RedirectResponse:
        if not get_house(house_id):
            raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")
        await send_analysis_zip_via_gmail(house_id)
        return RedirectResponse(f"../{house_id}", status_code=303)

    @app.post("/houses/{house_id}/gmail-import-results")
    async def gmail_import_house_results_route(house_id: str) -> RedirectResponse:
        if not get_house(house_id):
            raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")
        await import_gmail_results()
        return RedirectResponse(f"../{house_id}", status_code=303)
