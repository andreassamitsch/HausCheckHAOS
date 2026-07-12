from __future__ import annotations

import base64
import io
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from PIL import Image, UnidentifiedImageError

from app.analysis_package import analysis_schema, evidence_export, local_image_paths, public_house, source_export
from app.github_exchange import GitHubExchangeClient, load_settings
from app.storage import get_house, list_evidence, list_sources


OPTIONS_PATH = Path("/data/options.json")


def _load_options() -> dict[str, Any]:
    if not OPTIONS_PATH.exists():
        return {}
    try:
        return json.loads(OPTIONS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _clean_path(value: Any, default: str) -> str:
    text = str(value or default).strip().strip("/")
    text = re.sub(r"/{2,}", "/", text)
    return text or default


def _int_option(value: Any, default: int, min_value: int, max_value: int) -> int:
    try:
        result = int(float(str(value)))
    except Exception:
        result = default
    return max(min_value, min(result, max_value))


def b64_options() -> dict[str, Any]:
    data = _load_options()

    def opt(name: str, default: Any) -> Any:
        env = os.environ.get(f"HAUSCHECK_{name.upper()}")
        if env is not None:
            return env
        return data.get(name, default)

    return {
        "path": _clean_path(opt("github_b64_test_path", "ai_exchange/tests/base64"), "ai_exchange/tests/base64"),
        "image_limit": _int_option(opt("github_b64_image_limit", 1), 1, 1, 12),
        "image_max_size": _int_option(opt("github_b64_image_max_size", 1800), 1800, 400, 4096),
        "image_quality": _int_option(opt("github_b64_image_quality", 90), 90, 50, 98),
        "chunk_size": _int_option(opt("github_b64_chunk_size", 40000), 40000, 10000, 200000),
        "line_length": _int_option(opt("github_b64_line_length", 4000), 4000, 500, 8000),
    }


def _image_bytes_for_b64(path: Path, max_size: int, quality: int) -> tuple[bytes, dict[str, Any]]:
    original = path.read_bytes()
    meta: dict[str, Any] = {
        "original_file_name": path.name,
        "original_size_bytes": len(original),
        "export_format": "original_or_jpeg",
        "max_size": max_size,
        "quality": quality,
    }
    try:
        with Image.open(path) as image:
            meta["original_width"] = image.width
            meta["original_height"] = image.height
            meta["original_mode"] = image.mode
            # Nicht stark verkleinern: Wenn das Bild bereits innerhalb der Grenze liegt und JPG ist, original übernehmen.
            if image.width <= max_size and image.height <= max_size and path.suffix.lower() in {".jpg", ".jpeg"}:
                meta["export_width"] = image.width
                meta["export_height"] = image.height
                meta["export_format"] = "original_jpeg"
                meta["export_size_bytes"] = len(original)
                return original, meta

            image = image.convert("RGB")
            image.thumbnail((max_size, max_size))
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=quality, optimize=True)
            data = output.getvalue()
            meta["export_width"] = image.width
            meta["export_height"] = image.height
            meta["export_format"] = "jpeg_resized"
            meta["export_size_bytes"] = len(data)
            return data, meta
    except UnidentifiedImageError:
        meta["export_format"] = "original_unknown_image"
        meta["export_size_bytes"] = len(original)
        return original, meta


def _chunks(text: str, size: int) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)] or [""]


def _wrap_text(text: str, line_length: int) -> str:
    return "\n".join(text[i:i + line_length] for i in range(0, len(text), line_length)) + "\n"


def _prompt_text(house_id: str) -> str:
    return f"""# HausCheck Base64 Bildtest

Dieses Verzeichnis testet einen binärfreien GitHub-Bildtransport.

## Aufgabe

1. Lies `manifest.json`.
2. Lies pro Bild alle in `chunks` gelisteten `part_*.txt` Dateien.
3. Setze die Textteile exakt in Reihenfolge zusammen.
4. Entferne alle Whitespaces/Zeilenumbrüche aus dem Base64-Text.
5. Base64-decode den zusammengesetzten Text zu einer JPG-Datei.
6. Öffne das rekonstruierte Bild und prüfe, ob echte visuelle Analyse möglich ist.
7. Antworte zunächst nur mit einem kurzen Testergebnis: Bild decodierbar ja/nein, Bild sichtbar ja/nein, grobe Bildbeschreibung.

## Python-Beispiel

```python
import base64, json, re
from pathlib import Path

manifest = json.loads(Path('manifest.json').read_text())
for image in manifest['images']:
    raw = ''.join(Path(part).read_text() for part in image['chunks'])
    b64 = ''.join(raw.split())
    Path(image['output_file']).write_bytes(base64.b64decode(b64))
```

house_id: {house_id}
"""


async def export_base64_image_test(house_id: str) -> dict[str, Any]:
    settings = load_settings()
    if not settings.ready:
        raise HTTPException(status_code=400, detail="GitHub Exchange ist nicht vollständig konfiguriert")
    house = get_house(house_id)
    if not house:
        raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")

    opts = b64_options()
    images = local_image_paths(house_id)[: int(opts["image_limit"])]
    if not images:
        raise HTTPException(status_code=400, detail="Keine lokal geladenen Hausbilder gefunden")

    client = GitHubExchangeClient(settings)
    base_dir = f"{opts['path']}/{house_id}"
    manifest_images: list[dict[str, Any]] = []
    total_b64_chars = 0

    for index, (media, path) in enumerate(images, start=1):
        image_bytes, meta = _image_bytes_for_b64(path, int(opts["image_max_size"]), int(opts["image_quality"]))
        b64_text = base64.b64encode(image_bytes).decode("ascii")
        parts = _chunks(b64_text, int(opts["chunk_size"]))
        image_dir = f"{base_dir}/images/{index:02d}"
        chunk_paths: list[str] = []
        for part_index, part in enumerate(parts, start=1):
            part_path = f"{image_dir}/part_{part_index:03d}.txt"
            wrapped = _wrap_text(part, int(opts["line_length"]))
            await client.put_file(part_path, wrapped.encode("ascii"), f"HausCheck b64 image {house_id} {index:02d}/{part_index:03d}")
            chunk_paths.append(part_path)

        image_meta = {
            "index": index,
            "media_id": media.get("id"),
            "original_url": media.get("original_url"),
            "source_local_path": str(path),
            "mime_type": "image/jpeg",
            "output_file": f"image_{index:02d}.jpg",
            "base64_chars": len(b64_text),
            "chunk_count": len(parts),
            "line_length": int(opts["line_length"]),
            "chunks": chunk_paths,
            **meta,
        }
        await client.put_file(
            f"{image_dir}/meta.json",
            json.dumps(image_meta, ensure_ascii=False, indent=2).encode("utf-8"),
            f"HausCheck b64 image meta {house_id} {index:02d}",
        )
        manifest_images.append(image_meta)
        total_b64_chars += len(b64_text)

    manifest = {
        "kind": "hauscheck_base64_image_test",
        "version": 2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "house_id": house_id,
        "repo": settings.repo,
        "branch": settings.branch,
        "base_dir": base_dir,
        "options": opts,
        "house": public_house(house),
        "sources": [source_export(src) for src in list_sources(house_id)],
        "evidence": [evidence_export(item) for item in list_evidence(house_id)],
        "import_schema": analysis_schema(house_id),
        "images": manifest_images,
        "decode_instruction": "Concatenate chunk files in listed order, remove whitespace/newlines, base64-decode to output_file, then open as JPEG.",
        "decode_python": "raw=''.join(Path(p).read_text() for p in image['chunks']); b64=''.join(raw.split()); Path(image['output_file']).write_bytes(base64.b64decode(b64))",
    }
    await client.put_file(
        f"{base_dir}/manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        f"HausCheck b64 manifest {house_id}",
    )
    await client.put_file(
        f"{base_dir}/prompt.md",
        _prompt_text(house_id).encode("utf-8"),
        f"HausCheck b64 prompt {house_id}",
    )

    return {
        "house_id": house_id,
        "github_dir": base_dir,
        "image_count": len(manifest_images),
        "total_base64_chars": total_b64_chars,
        "chunk_count": sum(len(item["chunks"]) for item in manifest_images),
    }


def register_github_b64_export(app: FastAPI) -> None:
    @app.post("/houses/{house_id}/github-base64-test-export")
    async def github_base64_test_export_route(house_id: str) -> RedirectResponse:
        await export_base64_image_test(house_id)
        return RedirectResponse(f"../{house_id}", status_code=303)

    @app.post("/github/base64-test/{house_id}")
    async def github_base64_test_export_api(house_id: str) -> dict[str, Any]:
        return await export_base64_image_test(house_id)
