from __future__ import annotations

import json
import uuid
import zipfile
from pathlib import Path
from typing import Any, Callable

from app.storage import now_iso, project_dir


REQUEST_FILE = "analysis_request.json"
LOCAL_REQUEST_FILE = "latest_request.json"
_PATCHED = False
_ORIGINAL_CREATE_ZIP: Callable[[str], Path] | None = None


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


def _request_payload(house_id: str) -> dict[str, Any]:
    return {
        "kind": "hauscheck_analysis_request",
        "version": 1,
        "house_id": house_id,
        "analysis_request_id": uuid.uuid4().hex,
        "created_at": now_iso(),
    }


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
    request = _request_payload(house_id)
    _rewrite_package(target, request)
    local = latest_request_path(house_id)
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
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

    # Das Exposé-Modul hält je nach Registrierungsreihenfolge ebenfalls direkte Referenzen.
    if hasattr(expose_ai_export, "create_analysis_zip"):
        expose_ai_export.create_analysis_zip = create_analysis_zip_with_request

    _PATCHED = True
