from __future__ import annotations

import hashlib
import json
import re
import uuid
import zipfile
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.storage import now_iso, project_dir


REQUEST_FILE = "analysis_request.json"
LOCAL_REQUEST_FILE = "latest_request.json"
_PATCHED = False
_ORIGINAL_CREATE_ZIP: Callable[[str], Path] | None = None
_FORCE_NEW_REQUEST: ContextVar[bool] = ContextVar("hauscheck_force_new_analysis_request", default=False)

_VOLATILE_KEYS = {
    "analysis_request",
    "analysis_request_id",
    "created_at",
    "updated_at",
    "exported_at",
    "imported_at",
    "first_seen_at",
    "last_seen_at",
    "generated_at",
    "analysis_date",
    "timestamp",
}


def latest_request_path(house_id: str) -> Path:
    return project_dir(house_id) / "analysis" / LOCAL_REQUEST_FILE


def load_latest_request(house_id: str) -> dict[str, Any] | None:
    path = latest_request_path(house_id)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def save_latest_request(house_id: str, request: dict[str, Any]) -> None:
    local = latest_request_path(house_id)
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")


@contextmanager
def force_new_analysis_request() -> Iterator[None]:
    token = _FORCE_NEW_REQUEST.set(True)
    try:
        yield
    finally:
        _FORCE_NEW_REQUEST.reset(token)


def _compact_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _canonical_url(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        query = [
            (key, val)
            for key, val in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in {"ref", "source", "campaign"}
        ]
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(sorted(query)), ""))
    except Exception:
        return raw


def _clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _clean_json(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in _VOLATILE_KEYS
        }
    if isinstance(value, list):
        cleaned = [_clean_json(item) for item in value]
        try:
            return sorted(cleaned, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        except Exception:
            return cleaned
    if isinstance(value, str):
        return _compact_text(value)
    return value


def _semantic_listing(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except Exception:
        return {}
    if not isinstance(value, dict):
        return {}

    house = value.get("house") if isinstance(value.get("house"), dict) else {}
    clean_house = {
        key: _clean_json(val)
        for key, val in house.items()
        if key not in _VOLATILE_KEYS
    }

    clean_sources: list[dict[str, Any]] = []
    for source in value.get("sources") or []:
        if not isinstance(source, dict):
            continue
        clean_sources.append(
            {
                "source_name": _compact_text(source.get("source_name")),
                "source_url": _canonical_url(source.get("source_url")),
                "external_id": _compact_text(source.get("external_id")),
                "description": _compact_text(source.get("description")),
                "parser_status": _compact_text(source.get("parser_status")),
            }
        )
    clean_sources.sort(key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
    return {"house": clean_house, "sources": clean_sources}


def _semantic_evidence(raw: bytes) -> list[dict[str, Any]]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except Exception:
        return []
    entries = value.get("evidence") if isinstance(value, dict) else []
    result: list[dict[str, Any]] = []
    for item in entries or []:
        if not isinstance(item, dict):
            continue
        # source_text_snippet ist absichtlich ausgeschlossen: Parser können denselben
        # Fakt mit leicht anderem Ausschnitt oder Whitespace liefern.
        result.append(
            {
                "field_name": _compact_text(item.get("field_name")),
                "value_text": _compact_text(item.get("value_text")),
                "source_label": _compact_text(item.get("source_label")),
                "confidence": _compact_text(item.get("confidence")),
            }
        )
    result.sort(key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
    return result


def package_content_fingerprint(target: Path) -> str:
    """Fachlicher Fingerprint ohne Auftrags-ID, Zeitstempel und ZIP-Metadaten."""
    digest = hashlib.sha256()
    with zipfile.ZipFile(target, "r") as source:
        names = sorted(info.filename for info in source.infolist() if not info.is_dir())
        for name in names:
            if name in {REQUEST_FILE, "README_PROMPT.md"}:
                continue
            raw = source.read(name)
            if name == "listing.json":
                payload = _semantic_listing(raw)
                canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            elif name == "evidence.json":
                payload = _semantic_evidence(raw)
                canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            elif name.endswith(".json"):
                try:
                    payload = _clean_json(json.loads(raw.decode("utf-8")))
                    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                except Exception:
                    canonical = raw
            else:
                canonical = raw
            digest.update(name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(hashlib.sha256(canonical).digest())
    return digest.hexdigest()


def _request_payload(house_id: str, fingerprint: str, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    old = previous or {}
    reused = bool(
        not _FORCE_NEW_REQUEST.get()
        and old.get("analysis_request_id")
        and str(old.get("content_fingerprint") or "") == fingerprint
    )
    if reused:
        request = dict(old)
        request["reused_at"] = now_iso()
        request["reused"] = True
        return request
    return {
        "kind": "hauscheck_analysis_request",
        "version": 2,
        "house_id": house_id,
        "analysis_request_id": uuid.uuid4().hex,
        "created_at": now_iso(),
        "content_fingerprint": fingerprint,
        "reused": False,
    }


def mark_latest_request_uploaded(house_id: str, github_path: str) -> dict[str, Any] | None:
    request = load_latest_request(house_id)
    if not request:
        return None
    request["uploaded_at"] = now_iso()
    request["github_path"] = github_path
    save_latest_request(house_id, request)
    return request


def _rewrite_package(target: Path, request: dict[str, Any]) -> None:
    entries: dict[str, bytes] = {}
    with zipfile.ZipFile(target, "r") as source:
        for info in source.infolist():
            if not info.is_dir():
                entries[info.filename] = source.read(info.filename)

    listing: dict[str, Any] = {}
    try:
        listing = json.loads(entries.get("listing.json", b"{}").decode("utf-8"))
    except Exception:
        listing = {}
    if not isinstance(listing, dict):
        listing = {}
    listing["analysis_request"] = request
    entries["listing.json"] = json.dumps(listing, ensure_ascii=False, indent=2).encode("utf-8")

    schema: dict[str, Any] = {}
    try:
        schema = json.loads(entries.get("import_schema.json", b"{}").decode("utf-8"))
    except Exception:
        schema = {}
    if not isinstance(schema, dict):
        schema = {"type": "object"}
    required = schema.setdefault("required", [])
    if not isinstance(required, list):
        required = []
        schema["required"] = required
    if "analysis_request_id" not in required:
        required.append("analysis_request_id")
    properties = schema.setdefault("properties", {})
    if not isinstance(properties, dict):
        properties = {}
        schema["properties"] = properties
    properties["analysis_request_id"] = {
        "type": "string",
        "const": request["analysis_request_id"],
        "description": "Muss unverändert aus analysis_request.json übernommen werden.",
    }
    entries["import_schema.json"] = json.dumps(schema, ensure_ascii=False, indent=2).encode("utf-8")

    prompt = entries.get("README_PROMPT.md", b"").decode("utf-8", errors="replace")
    prompt += f"""

## Eindeutige Analyse-Auftragskennung

Dieses Paket gehört ausschließlich zu folgendem Auftrag:

```text
analysis_request_id: {request['analysis_request_id']}
```

Lies `analysis_request.json` und übernimm `analysis_request_id` **unverändert** in
`hauscheck_analysis.json`. Verwende kein Ergebnis aus einem älteren Paket und kopiere keine
frühere Analyse. Ohne die passende Auftragskennung darf HausCheck das Ergebnis nicht als Antwort
auf diesen Export akzeptieren.
"""
    entries["README_PROMPT.md"] = prompt.encode("utf-8")
    entries[REQUEST_FILE] = json.dumps(request, ensure_ascii=False, indent=2).encode("utf-8")

    temporary = target.with_name(target.name + ".request.tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for name, content in entries.items():
            output.writestr(name, content)
    temporary.replace(target)


def create_analysis_zip_with_request(house_id: str) -> Path:
    if _ORIGINAL_CREATE_ZIP is None:
        raise RuntimeError("Analyseexport ist noch nicht registriert")
    target = _ORIGINAL_CREATE_ZIP(house_id)
    fingerprint = package_content_fingerprint(target)
    request = _request_payload(house_id, fingerprint, load_latest_request(house_id))
    _rewrite_package(target, request)
    save_latest_request(house_id, request)
    return target


def register_analysis_request_guard() -> None:
    global _PATCHED, _ORIGINAL_CREATE_ZIP
    if _PATCHED:
        return

    import app.analysis_package as analysis_package
    import app.expose_ai_export as expose_ai_export
    import app.github_auto_export as github_auto_export
    import app.github_exchange as github_exchange
    import app.gmail_exchange as gmail_exchange

    _ORIGINAL_CREATE_ZIP = analysis_package.create_analysis_zip
    analysis_package.create_analysis_zip = create_analysis_zip_with_request
    github_auto_export.create_analysis_zip = create_analysis_zip_with_request
    github_exchange.create_analysis_zip = create_analysis_zip_with_request
    gmail_exchange.create_analysis_zip = create_analysis_zip_with_request

    if hasattr(expose_ai_export, "create_analysis_zip"):
        expose_ai_export.create_analysis_zip = create_analysis_zip_with_request

    _PATCHED = True
