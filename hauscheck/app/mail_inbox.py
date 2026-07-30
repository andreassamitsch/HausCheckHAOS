from __future__ import annotations

import asyncio
import hashlib
import imaplib
import inspect
import json
import os
import re
import shutil
from dataclasses import dataclass
from email import policy
from email.message import Message
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import quote
from typing import Any, Callable

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

import app.modern_ui as modern_ui
from app.github_auto_export import auto_export_house_to_github
from app.mail_import import SavedInput, _copy_artifacts_to_house, _process_saved_inputs
from app.pipeline_status import set_pipeline_stage
from app.storage import (
    DATA_DIR,
    add_evidence,
    create_house,
    create_source,
    get_house,
    list_houses,
    now_iso,
)
from app.ui_helpers import esc


OPTIONS_PATH = Path("/data/options.json")
INBOX_ROOT = DATA_DIR / "mail_inbox"
MAX_MESSAGE_BYTES = 60 * 1024 * 1024
VALID_ITEM_ID = re.compile(r"^[a-f0-9]{16}$")
FORWARD_PREFIX = re.compile(r"^\s*(?:(?:re|aw|wg|fw|fwd)\s*:\s*)+", re.IGNORECASE)
_mail_inbox_task: asyncio.Task | None = None


@dataclass
class MailInboxSettings:
    enabled: bool = False
    imap_host: str = ""
    imap_port: int = 993
    username: str = ""
    password: str = ""
    folder: str = "INBOX"
    interval_minutes: int = 2
    mark_seen: bool = True

    @property
    def ready(self) -> bool:
        return bool(self.enabled and self.imap_host and self.username and self.password)


def _load_options() -> dict[str, Any]:
    if not OPTIONS_PATH.exists():
        return {}
    try:
        data = json.loads(OPTIONS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().casefold()
    if text in {"1", "true", "yes", "on", "ja"}:
        return True
    if text in {"0", "false", "no", "off", "nein"}:
        return False
    return default


def _int_option(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        result = int(float(str(value)))
    except Exception:
        result = default
    return max(minimum, min(result, maximum))


def load_mail_inbox_settings() -> MailInboxSettings:
    data = _load_options()

    def option(name: str, default: Any = "") -> Any:
        env = os.environ.get(f"HAUSCHECK_{name.upper()}")
        return env if env is not None else data.get(name, default)

    return MailInboxSettings(
        enabled=_truthy(option("mail_inbox_enabled", False), False),
        imap_host=str(option("mail_inbox_imap_host", "") or "").strip(),
        imap_port=_int_option(option("mail_inbox_imap_port", 993), 993, 1, 65535),
        username=str(option("mail_inbox_username", "") or "").strip(),
        password=str(option("mail_inbox_password", "") or "").strip(),
        folder=str(option("mail_inbox_folder", "INBOX") or "INBOX").strip(),
        interval_minutes=_int_option(option("mail_inbox_interval_minutes", 2), 2, 1, 1440),
        mark_seen=_truthy(option("mail_inbox_mark_seen", True), True),
    )


def _atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _item_dir(item_id: str) -> Path:
    if not VALID_ITEM_ID.fullmatch(item_id or ""):
        raise HTTPException(status_code=400, detail="Ungültige E-Mail-Kennung")
    return INBOX_ROOT / item_id


def _strip_forward_prefix(subject: str) -> str:
    cleaned = FORWARD_PREFIX.sub("", str(subject or "")).strip()
    return cleaned or "Neue Hausakte aus E-Mail"


def _item_id(message_id: str, content_hash: str) -> str:
    key = message_id.strip().strip("<>") or content_hash
    return hashlib.sha256(key.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _message_header(message: Message, name: str) -> str:
    return re.sub(r"\s+", " ", str(message.get(name, "") or "")).strip()


def _message_meta(message: Message, raw_hash: str, imap_id: str) -> dict[str, Any]:
    message_id = _message_header(message, "Message-ID").strip("<>")
    return {
        "id": _item_id(message_id, raw_hash),
        "status": "pending",
        "subject": _message_header(message, "Subject") or "(ohne Betreff)",
        "sender": _message_header(message, "From"),
        "recipient": _message_header(message, "To"),
        "message_date": _message_header(message, "Date"),
        "message_id": message_id,
        "imap_id": imap_id,
        "content_hash": raw_hash,
        "received_at": now_iso(),
        "assigned_house_id": None,
        "assigned_at": None,
        "ignored_at": None,
        "error": None,
    }


def _capture_raw_message(raw: bytes, imap_id: str = "") -> tuple[dict[str, Any], bool]:
    if not raw:
        raise ValueError("Leere E-Mail")
    if len(raw) > MAX_MESSAGE_BYTES:
        raise ValueError("E-Mail ist größer als 60 MB")

    message = BytesParser(policy=policy.default).parsebytes(raw)
    raw_hash = hashlib.sha256(raw).hexdigest()
    meta = _message_meta(message, raw_hash, imap_id)
    item_dir = INBOX_ROOT / meta["id"]
    meta_path = item_dir / "meta.json"

    if meta_path.exists():
        existing = _load_json(meta_path)
        return existing or meta, False

    upload_dir = item_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=False)
    original = upload_dir / "original.eml"
    original.write_bytes(raw)

    try:
        saved = [
            SavedInput(
                filename="original.eml",
                path=original,
                mime_type="message/rfc822",
                source_key=f"inbox:{meta['id']}",
                source_label=f"E-Mail „{meta['subject']}“",
            )
        ]
        manifest = _process_saved_inputs(item_dir, saved)
        manifest["inbox_id"] = meta["id"]
        manifest["mail_meta"] = {
            key: meta.get(key)
            for key in ("subject", "sender", "recipient", "message_date", "message_id", "received_at")
        }
        _atomic_json(item_dir / "manifest.json", manifest)
        _atomic_json(meta_path, meta)
        return meta, True
    except Exception:
        shutil.rmtree(item_dir, ignore_errors=True)
        raise


def _imap_fetch_sync(settings: MailInboxSettings) -> dict[str, Any]:
    INBOX_ROOT.mkdir(parents=True, exist_ok=True)
    checked = 0
    added: list[dict[str, Any]] = []
    duplicates = 0
    errors: list[dict[str, str]] = []

    with imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port) as imap:
        imap.login(settings.username, settings.password)
        status, _ = imap.select(settings.folder or "INBOX")
        if status != "OK":
            raise RuntimeError(f"IMAP-Ordner konnte nicht geöffnet werden: {settings.folder}")

        status, data = imap.search(None, "UNSEEN")
        if status != "OK":
            raise RuntimeError("IMAP-Suche fehlgeschlagen")

        for message_number in (data[0] or b"").split():
            checked += 1
            imap_id = message_number.decode(errors="ignore")
            try:
                status, payload = imap.fetch(message_number, "(RFC822)")
                if status != "OK" or not payload or not payload[0]:
                    raise ValueError("E-Mail konnte nicht gelesen werden")
                raw = payload[0][1]
                if not isinstance(raw, bytes):
                    raise ValueError("E-Mail-Inhalt fehlt")

                message = BytesParser(policy=policy.default).parsebytes(raw)
                subject = _message_header(message, "Subject").upper()
                if "HAUSCHECK_RESULT" in subject or "HAUSCHECK_EXPORT" in subject:
                    continue

                meta, created = _capture_raw_message(raw, imap_id)
                if created:
                    added.append(meta)
                else:
                    duplicates += 1
                if settings.mark_seen:
                    imap.store(message_number, "+FLAGS", "\\Seen")
            except Exception as exc:
                errors.append({"imap_id": imap_id, "error": str(exc)[:500]})

    return {
        "checked": checked,
        "added": added,
        "duplicates": duplicates,
        "errors": errors,
    }


async def fetch_mail_inbox() -> dict[str, Any]:
    settings = load_mail_inbox_settings()
    if not settings.ready:
        return {
            "checked": 0,
            "added": [],
            "duplicates": 0,
            "errors": [],
            "disabled": True,
        }
    return await asyncio.to_thread(_imap_fetch_sync, settings)


def _all_items() -> list[dict[str, Any]]:
    INBOX_ROOT.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for path in INBOX_ROOT.iterdir():
        if not path.is_dir() or not VALID_ITEM_ID.fullmatch(path.name):
            continue
        meta = _load_json(path / "meta.json")
        if meta:
            items.append(meta)
    items.sort(key=lambda item: str(item.get("received_at") or ""), reverse=True)
    return items


def _load_item(item_id: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    item_dir = _item_dir(item_id)
    meta = _load_json(item_dir / "meta.json")
    manifest = _load_json(item_dir / "manifest.json")
    if not meta or not manifest:
        raise HTTPException(status_code=404, detail="E-Mail nicht gefunden")
    return item_dir, meta, manifest


def _save_meta(item_dir: Path, meta: dict[str, Any]) -> None:
    _atomic_json(item_dir / "meta.json", meta)


def _count_artifacts(manifest: dict[str, Any]) -> tuple[int, int]:
    artifacts = manifest.get("artifacts") or []
    documents = sum(1 for item in artifacts if item.get("classification") != "Original-E-Mail")
    return len(artifacts), documents


def _inbox_card(item: dict[str, Any]) -> str:
    item_id = str(item.get("id") or "")
    status = str(item.get("status") or "pending")
    label = {
        "pending": "Zuordnung erforderlich",
        "assigned": "Zugeordnet",
        "ignored": "Ignoriert",
    }.get(status, status)
    details = ""
    try:
        manifest = _load_json(_item_dir(item_id) / "manifest.json")
        artifact_count, document_count = _count_artifacts(manifest)
        details = f"{artifact_count} Dateien · {document_count} Anhänge/Bilder"
    except Exception:
        details = "Inhalt noch nicht verfügbar"
    assigned = ""
    if item.get("assigned_house_id"):
        house = get_house(str(item.get("assigned_house_id")))
        if house:
            assigned = f"<p><strong>Hausakte:</strong> {esc(house.get('title'))}</p>"
    return f"""
    <div class="card">
      <div class="action-row" style="justify-content:space-between;align-items:flex-start">
        <div>
          <span class="pill">{esc(label)}</span>
          <h2 style="margin-top:10px">{esc(item.get('subject') or '(ohne Betreff)')}</h2>
        </div>
        <a class="button ghost" href="mail-inbox/{esc(item_id)}">Öffnen</a>
      </div>
      <p><strong>Von:</strong> {esc(item.get('sender') or 'unbekannt')}</p>
      <p class="muted">{esc(item.get('message_date') or item.get('received_at') or '')}</p>
      <p class="muted">{esc(details)}</p>
      {assigned}
    </div>
    """


def _mail_inbox_page(message: str = "") -> HTMLResponse:
    settings = load_mail_inbox_settings()
    items = _all_items()
    pending = [item for item in items if item.get("status") == "pending"]
    processed = [item for item in items if item.get("status") != "pending"]
    notice = f'<div class="card notice">{esc(message)}</div>' if message else ""
    if settings.ready:
        state = (
            f"<span class='pill'>Postfach aktiv</span>"
            f"<p class='muted'>{esc(settings.username)} · {esc(settings.imap_host)}:{settings.imap_port}"
            f" · Abruf alle {settings.interval_minutes} Minuten</p>"
        )
    else:
        state = (
            "<span class='pill'>Postfach noch nicht eingerichtet</span>"
            "<p class='muted'>IMAP-Zugangsdaten in den Add-on-Einstellungen eintragen und den E-Mail-Posteingang aktivieren.</p>"
        )

    pending_html = "".join(_inbox_card(item) for item in pending)
    processed_html = "".join(_inbox_card(item) for item in processed[:30])
    body = f"""
    <div class="page-heading">
      <div><h1>E-Mail-Posteingang</h1><p>Neue E-Mails werden nur gesammelt. Die Zuordnung erfolgt immer manuell.</p></div>
      <a class="button ghost" href="./">{modern_ui.icon('back')} Zurück</a>
    </div>
    {notice}
    <div class="card">
      <div class="action-row" style="justify-content:space-between">
        <div>{state}</div>
        <form method="post" action="mail-inbox/refresh" data-loading="Postfach wird geprüft …">
          <button type="submit">Postfach jetzt prüfen</button>
        </form>
      </div>
    </div>
    <div class="section">
      <h2>Zuordnung erforderlich <span class="pill">{len(pending)}</span></h2>
      <div class="grid">{pending_html or '<div class="card"><p class="muted">Keine unzugeordneten E-Mails.</p></div>'}</div>
    </div>
    <div class="section">
      <details {'open' if processed and not pending else ''}>
        <summary><strong>Bearbeitete E-Mails ({len(processed)})</strong></summary>
        <div class="grid section">{processed_html or '<p class="muted">Noch keine bearbeiteten E-Mails.</p>'}</div>
      </details>
    </div>
    """
    return modern_ui.modern_layout("E-Mail-Posteingang", body, home_href="./")


def _artifact_rows(manifest: dict[str, Any]) -> str:
    rows = []
    for item in manifest.get("artifacts") or []:
        rows.append(
            "<tr>"
            f"<td><strong>{esc(item.get('original_filename') or item.get('filename'))}</strong></td>"
            f"<td>{esc(item.get('classification') or 'Dokument')}</td>"
            f"<td>{esc(item.get('source_label') or '')}</td>"
            "</tr>"
        )
    return "".join(rows) or '<tr><td colspan="3" class="muted">Keine Anhänge erkannt.</td></tr>'


def _detail_page(item_id: str, meta: dict[str, Any], manifest: dict[str, Any]) -> HTMLResponse:
    houses = list_houses()
    house_options = "".join(
        f'<option value="{esc(house.get("id"))}">{esc(house.get("title"))}'
        f'{f" · {esc(house.get("location_text"))}" if house.get("location_text") else ""}</option>'
        for house in sorted(houses, key=lambda item: str(item.get("title") or "").casefold())
    )
    warnings = "".join(f"<li>{esc(item)}</li>" for item in manifest.get("warnings") or [])
    fields = manifest.get("fields") or {}
    field_rows = "".join(
        f"<tr><td>{esc(key)}</td><td>{esc(value)}</td></tr>"
        for key, value in fields.items()
        if value not in (None, "")
    ) or '<tr><td colspan="2" class="muted">Keine eindeutigen Objektdaten erkannt.</td></tr>'
    disabled = meta.get("status") == "assigned"
    assigned_note = ""
    if disabled:
        house = get_house(str(meta.get("assigned_house_id") or ""))
        assigned_note = (
            f'<div class="card notice"><strong>Bereits zugeordnet:</strong> '
            f'{esc((house or {}).get("title") or meta.get("assigned_house_id"))}</div>'
        )
    body = f"""
    <div class="page-heading">
      <div><h1>{esc(meta.get('subject') or '(ohne Betreff)')}</h1><p>Von {esc(meta.get('sender') or 'unbekannt')}</p></div>
      <a class="button ghost" href="../mail-inbox">{modern_ui.icon('back')} Posteingang</a>
    </div>
    {assigned_note}
    <div class="card">
      <p><strong>Betreff:</strong> {esc(meta.get('subject'))}</p>
      <p><strong>Absender:</strong> {esc(meta.get('sender'))}</p>
      <p><strong>Datum:</strong> {esc(meta.get('message_date') or meta.get('received_at'))}</p>
    </div>
    <div class="card section">
      <h2>Manuell zuordnen</h2>
      <form method="post" action="assign" data-loading="E-Mail und Anhänge werden übernommen …">
        <label>Bestehende Hausakte</label>
        <select name="house_id">
          <option value="">— keine auswählen, neue Hausakte anlegen —</option>
          {house_options}
        </select>
        <label>Oder neue Hausakte als Entwurf</label>
        <input name="new_title" value="{esc(_strip_forward_prefix(str(meta.get('subject') or '')))}">
        <p class="muted">HausCheck ordnet niemals automatisch zu. Eine bestehende Hausakte hat Vorrang; ansonsten wird der eingegebene Titel verwendet.</p>
        <label style="display:flex;align-items:center;gap:10px">
          <input style="width:auto;margin:0" type="checkbox" name="start_analysis" value="1" checked>
          Nach der Zuordnung die KI-Analyse aktualisieren
        </label>
        <div class="action-row section">
          <button type="submit" {'disabled' if disabled else ''}>Zuordnen</button>
        </div>
      </form>
      <form method="post" action="ignore" data-no-loading="true">
        <button type="submit" class="secondary">E-Mail ignorieren</button>
      </form>
    </div>
    <div class="card section">
      <h2>Erkannte Daten</h2>
      <table><tr><th>Feld</th><th>Wert</th></tr>{field_rows}</table>
    </div>
    <div class="card section">
      <h2>Dokumente und Bilder</h2>
      <table><tr><th>Datei</th><th>Typ</th><th>Quelle</th></tr>{_artifact_rows(manifest)}</table>
    </div>
    {f'<div class="card section notice warning"><h2>Prüfhinweise</h2><ul>{warnings}</ul></div>' if warnings else ''}
    """
    return modern_ui.modern_layout("E-Mail zuordnen", body, home_href="../../")


def _new_house_data(title: str, manifest: dict[str, Any]) -> dict[str, Any]:
    fields = manifest.get("fields") or {}
    return {
        "title": title,
        "status": "new",
        "location_text": fields.get("location_text"),
        "address_status": fields.get("address_status") or "review",
        "price_eur": fields.get("price_eur"),
        "living_area_m2": fields.get("living_area_m2"),
        "plot_area_m2": fields.get("plot_area_m2"),
        "rooms": fields.get("rooms"),
        "year_built": fields.get("year_built"),
        "heating": fields.get("heating"),
        "energy_hwb": fields.get("energy_hwb"),
        "energy_fgee": fields.get("energy_fgee"),
        "energy_class_hwb": fields.get("energy_class_hwb"),
        "energy_class_fgee": fields.get("energy_class_fgee"),
        "notes": "Aus dem HausCheck-E-Mail-Posteingang angelegt.",
    }


def _attach_to_house(
    item_dir: Path,
    item_id: str,
    meta: dict[str, Any],
    manifest: dict[str, Any],
    house_id: str,
) -> dict[str, int]:
    warnings = manifest.get("warnings") or []
    source_ids: dict[str, str] = {}
    for source in manifest.get("sources") or []:
        key = str(source.get("key") or f"inbox:{item_id}")
        label = str(source.get("label") or f"E-Mail „{meta.get('subject') or '(ohne Betreff)'}“")
        source_row = create_source(
            house_id,
            {
                "source_name": label[:180],
                "source_url": f"mail-inbox://{item_id}/{hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]}",
                "external_id": source.get("message_id") or meta.get("message_id") or None,
                "description": " · ".join(
                    str(part)
                    for part in (
                        source.get("subject") or meta.get("subject"),
                        source.get("sender") or meta.get("sender"),
                        source.get("date") or meta.get("message_date"),
                    )
                    if part
                ),
                "parser_status": "partial" if warnings else "success",
                "parser_warnings": warnings,
            },
        )
        source_ids[key] = str(source_row["id"])

    if not source_ids:
        source_row = create_source(
            house_id,
            {
                "source_name": f"E-Mail „{meta.get('subject') or '(ohne Betreff)'}“",
                "source_url": f"mail-inbox://{item_id}/original",
                "external_id": meta.get("message_id") or None,
                "description": " · ".join(
                    str(part)
                    for part in (meta.get("subject"), meta.get("sender"), meta.get("message_date"))
                    if part
                ),
                "parser_status": "partial" if warnings else "success",
                "parser_warnings": warnings,
            },
        )
        source_ids[f"inbox:{item_id}"] = str(source_row["id"])

    fallback_source_id = next(iter(source_ids.values()))
    grouped: dict[str, list[dict[str, Any]]] = {}
    for evidence in manifest.get("evidence") or []:
        grouped.setdefault(str(evidence.get("source_key") or ""), []).append(evidence)
    for source_key, entries in grouped.items():
        add_evidence(house_id, source_ids.get(source_key) or fallback_source_id, entries)

    return _copy_artifacts_to_house(item_dir, manifest, house_id, source_ids)


async def _mail_inbox_loop() -> None:
    await asyncio.sleep(20)
    while True:
        settings = load_mail_inbox_settings()
        sleep_seconds = max(60, settings.interval_minutes * 60)
        try:
            if settings.ready:
                result = await fetch_mail_inbox()
                added = result.get("added") or []
                errors = result.get("errors") or []
                if added or errors:
                    print(
                        f"HausCheck E-Mail-Posteingang: neu={len(added)}, fehler={len(errors)}",
                        flush=True,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"HausCheck E-Mail-Posteingang fehlgeschlagen: {exc}", flush=True)
        await asyncio.sleep(sleep_seconds)


def _methods(route: Any) -> set[str]:
    return set(getattr(route, "methods", set()) or set())


def _take_route(app: FastAPI, path: str, method: str) -> Callable[..., Any] | None:
    for route in list(app.router.routes):
        if getattr(route, "path", "") == path and method in _methods(route):
            app.router.routes.remove(route)
            return getattr(route, "endpoint", None)
    return None


async def _call(endpoint: Callable[..., Any], **kwargs: Any) -> Any:
    result = endpoint(**kwargs)
    return await result if inspect.isawaitable(result) else result


def _add_inbox_to_import_page(response: Any) -> Any:
    if not isinstance(response, HTMLResponse):
        return response
    html = response.body.decode(response.charset or "utf-8", errors="replace")
    marker = '<div class="card section notice">'
    card = """
    <div class="card section">
      <div class="action-row" style="justify-content:space-between;align-items:center">
        <div><h2>E-Mail-Posteingang</h2><p class="muted">Weitergeleitete E-Mails abrufen und manuell einer Hausakte zuordnen.</p></div>
        <a class="button" href="mail-inbox">Posteingang öffnen</a>
      </div>
    </div>
    """
    html = html.replace(marker, card + marker, 1) if marker in html else html + card
    headers = {
        key: value
        for key, value in response.headers.items()
        if key.casefold() not in {"content-length", "content-type"}
    }
    return HTMLResponse(html, status_code=response.status_code, headers=headers)


def register_mail_inbox(app: FastAPI) -> None:
    import_endpoint = _take_route(app, "/import", "GET")

    if import_endpoint is not None:
        @app.get("/import", response_class=HTMLResponse)
        async def import_with_mail_inbox() -> Any:
            return _add_inbox_to_import_page(await _call(import_endpoint))

    @app.on_event("startup")
    async def start_mail_inbox() -> None:
        global _mail_inbox_task
        INBOX_ROOT.mkdir(parents=True, exist_ok=True)
        if _mail_inbox_task is None or _mail_inbox_task.done():
            _mail_inbox_task = asyncio.create_task(_mail_inbox_loop())
            print("HausCheck E-Mail-Posteingang gestartet", flush=True)

    @app.on_event("shutdown")
    async def stop_mail_inbox() -> None:
        global _mail_inbox_task
        if _mail_inbox_task and not _mail_inbox_task.done():
            _mail_inbox_task.cancel()
        _mail_inbox_task = None

    @app.get("/mail-inbox", response_class=HTMLResponse)
    def mail_inbox(message: str | None = None) -> HTMLResponse:
        return _mail_inbox_page(str(message or ""))

    @app.post("/mail-inbox/refresh")
    async def refresh_mail_inbox() -> RedirectResponse:
        result = await fetch_mail_inbox()
        if result.get("disabled"):
            message = "Postfach ist noch nicht eingerichtet."
        else:
            message = (
                f"Geprüft: {result.get('checked', 0)} · "
                f"neu: {len(result.get('added') or [])} · "
                f"Fehler: {len(result.get('errors') or [])}"
            )
        return RedirectResponse(f"../mail-inbox?message={quote(message)}", status_code=303)

    @app.get("/mail-inbox/{item_id}", response_class=HTMLResponse)
    def mail_inbox_detail(item_id: str) -> HTMLResponse:
        _, meta, manifest = _load_item(item_id)
        return _detail_page(item_id, meta, manifest)

    @app.post("/mail-inbox/{item_id}/assign")
    async def assign_mail(
        item_id: str,
        house_id: str | None = Form(None),
        new_title: str | None = Form(None),
        start_analysis: int = Form(0),
    ) -> RedirectResponse:
        item_dir, meta, manifest = _load_item(item_id)
        if meta.get("status") == "assigned":
            return RedirectResponse(f"../../houses/{meta.get('assigned_house_id')}", status_code=303)

        selected_house_id = str(house_id or "").strip()
        if selected_house_id:
            if not get_house(selected_house_id):
                raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")
        else:
            title = re.sub(r"\s+", " ", str(new_title or "")).strip()
            if not title:
                raise HTTPException(status_code=400, detail="Titel für die neue Hausakte fehlt")
            selected_house_id = str(create_house(_new_house_data(title[:180], manifest))["id"])

        counts = _attach_to_house(item_dir, item_id, meta, manifest, selected_house_id)
        summary = (
            f"E-Mail zugeordnet: {counts.get('images', 0)} Bilder, "
            f"{counts.get('pdfs', 0)} PDFs, {counts.get('emails', 0)} Original-E-Mails"
        )
        set_pipeline_stage(selected_house_id, "media_ready", "ok", summary)

        meta["status"] = "assigned"
        meta["assigned_house_id"] = selected_house_id
        meta["assigned_at"] = now_iso()
        _save_meta(item_dir, meta)

        if start_analysis:
            set_pipeline_stage(
                selected_house_id,
                "exporting",
                "running",
                "Neue E-Mail-Unterlagen wurden zugeordnet. KI-Analyse wird aktualisiert.",
            )
            try:
                started = bool(await auto_export_house_to_github(selected_house_id))
                if not started:
                    set_pipeline_stage(
                        selected_house_id,
                        "media_ready",
                        "ok",
                        summary + " · KI-Export ist derzeit nicht konfiguriert",
                    )
            except Exception as exc:
                set_pipeline_stage(
                    selected_house_id,
                    "error",
                    "error",
                    "E-Mail wurde zugeordnet, KI-Export ist fehlgeschlagen.",
                    error=str(exc)[:800],
                )

        return RedirectResponse(f"../../houses/{selected_house_id}", status_code=303)

    @app.post("/mail-inbox/{item_id}/ignore")
    def ignore_mail(item_id: str) -> RedirectResponse:
        item_dir, meta, _ = _load_item(item_id)
        meta["status"] = "ignored"
        meta["ignored_at"] = now_iso()
        _save_meta(item_dir, meta)
        return RedirectResponse("../", status_code=303)
