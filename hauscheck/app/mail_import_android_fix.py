from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse


SUPPORTED_EXTENSIONS = {".eml", ".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
MIME_EXTENSION_MAP = {
    "message/rfc822": ".eml",
    "application/eml": ".eml",
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "image/heif": ".heif",
}
GENERIC_MIME_TYPES = {
    "",
    "application/octet-stream",
    "binary/octet-stream",
    "text/plain",
}


def _methods(route: Any) -> set[str]:
    return set(getattr(route, "methods", set()) or set())


def _take_route(app: FastAPI, path: str, method: str) -> Callable[..., Any] | None:
    for route in list(app.router.routes):
        if getattr(route, "path", "") == path and method in _methods(route):
            app.router.routes.remove(route)
            return getattr(route, "endpoint", None)
    return None


def _clean_mime(value: str | None) -> str:
    return str(value or "").split(";", 1)[0].strip().casefold()


def _looks_like_eml(sample: bytes) -> bool:
    if not sample or b"\x00" in sample[:4096]:
        return False
    header_bytes = re.split(br"\r?\n\r?\n", sample[:262_144], maxsplit=1)[0]
    try:
        headers = header_bytes.decode("utf-8", errors="replace")
    except Exception:
        return False
    names = {match.group(1).casefold() for match in re.finditer(r"(?m)^([A-Za-z0-9-]{2,40}):", headers)}
    core = names & {"from", "to", "subject", "date", "message-id"}
    transport = names & {"mime-version", "content-type", "received", "delivered-to", "return-path"}
    return len(core) >= 2 and bool(transport)


def _sniff_extension(sample: bytes, mime_type: str | None = None) -> str | None:
    mime = _clean_mime(mime_type)
    mapped = MIME_EXTENSION_MAP.get(mime)
    if mapped:
        return mapped
    if sample.startswith(b"%PDF-"):
        return ".pdf"
    if sample.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if sample.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if len(sample) >= 12 and sample[:4] == b"RIFF" and sample[8:12] == b"WEBP":
        return ".webp"
    if len(sample) >= 12 and sample[4:8] == b"ftyp":
        brand = sample[8:12].casefold()
        if brand in {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"}:
            return ".heic" if brand.startswith(b"hei") else ".heif"
    if mime in GENERIC_MIME_TYPES and _looks_like_eml(sample):
        return ".eml"
    return None


def _filename_with_extension(filename: str | None, extension: str) -> str:
    name = Path(str(filename or "upload").replace("\\", "/")).name.strip(" .") or "upload"
    suffix = Path(name).suffix.casefold()
    if suffix in SUPPORTED_EXTENSIONS:
        return name
    if suffix:
        name = name[: -len(suffix)] or "upload"
    return f"{name}{extension}"


async def _normalize_upload_filename(upload: UploadFile) -> None:
    current = str(upload.filename or "")
    if Path(current).suffix.casefold() in SUPPORTED_EXTENSIONS:
        return

    mime = _clean_mime(upload.content_type)
    extension = MIME_EXTENSION_MAP.get(mime)
    if extension is None:
        sample = await upload.read(262_144)
        await upload.seek(0)
        extension = _sniff_extension(sample, mime)
    if extension:
        upload.filename = _filename_with_extension(current, extension)


async def _call(endpoint: Callable[..., Any], **kwargs: Any) -> Any:
    result = endpoint(**kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


def _relax_import_page(response: Any) -> Any:
    if not isinstance(response, HTMLResponse):
        return response
    html = response.body.decode(response.charset or "utf-8", errors="replace")
    html = re.sub(r'accept="[^"]*"', 'accept="*/*"', html, count=1)
    html = html.replace(
        "Beide .eml-Dateien können gleichzeitig gewählt werden.",
        "Mehrere .eml-Dateien können gleichzeitig gewählt werden. Android meldet E-Mail-Dateien teils als unbekannten Dateityp; HausCheck erkennt sie sicher anhand des Inhalts.",
    )
    headers = {
        key: value
        for key, value in response.headers.items()
        if key.casefold() not in {"content-length", "content-type"}
    }
    return HTMLResponse(html, status_code=response.status_code, headers=headers)


def register_mail_import_android_fix(app: FastAPI) -> None:
    import_endpoint = _take_route(app, "/import", "GET")
    preview_endpoint = _take_route(app, "/import/mail/preview", "POST")
    if import_endpoint is None or preview_endpoint is None:
        return

    @app.get("/import", response_class=HTMLResponse)
    async def import_choice_android() -> Any:
        return _relax_import_page(await _call(import_endpoint))

    @app.post("/import/mail/preview", response_class=HTMLResponse)
    async def preview_mail_import_android(files: list[UploadFile] = File(...)) -> Any:
        for upload in files:
            await _normalize_upload_filename(upload)
        return await _call(preview_endpoint, files=files)
