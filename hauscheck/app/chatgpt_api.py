from __future__ import annotations

import base64
import io
import json
import os
import secrets
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from PIL import Image, UnidentifiedImageError

from app.storage import (
    PROJECTS_DIR,
    get_house,
    get_media,
    list_evidence,
    list_houses,
    list_media,
    list_search_candidates,
    list_search_profiles,
    list_sources,
    source_url_exists,
)

SERVER_NAME = "hauscheck-mcp"
MCP_PROTOCOL_VERSION = "2024-11-05"


def configured_token() -> str:
    return os.environ.get("HAUSCHECK_API_TOKEN", "").strip()


def check_api_auth(request: Request) -> None:
    token = configured_token()
    if not token:
        raise HTTPException(status_code=503, detail="HausCheck API/MCP ist deaktiviert. Bitte api_token in den Add-on-Optionen setzen.")

    authorization = request.headers.get("authorization", "")
    provided = ""
    if authorization.lower().startswith("bearer "):
        provided = authorization.split(" ", 1)[1].strip()
    if not provided:
        provided = request.headers.get("x-hauscheck-token", "").strip()
    if not provided:
        provided = str(request.query_params.get("token") or "").strip()

    if not secrets.compare_digest(provided, token):
        raise HTTPException(status_code=401, detail="Ungültiger API-Token")


def public_house(house: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": house.get("id"),
        "title": house.get("title"),
        "status": house.get("status"),
        "location_text": house.get("location_text"),
        "address_status": house.get("address_status"),
        "price_eur": house.get("price_eur"),
        "living_area_m2": house.get("living_area_m2"),
        "plot_area_m2": house.get("plot_area_m2"),
        "rooms": house.get("rooms"),
        "year_built": house.get("year_built"),
        "heating": house.get("heating"),
        "energy_hwb": house.get("energy_hwb"),
        "energy_fgee": house.get("energy_fgee"),
        "energy_class_hwb": house.get("energy_class_hwb"),
        "energy_class_fgee": house.get("energy_class_fgee"),
        "created_at": house.get("created_at"),
        "updated_at": house.get("updated_at"),
    }


def public_source(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": source.get("id"),
        "source_name": source.get("source_name"),
        "source_url": source.get("source_url"),
        "external_id": source.get("external_id"),
        "parser_status": source.get("parser_status"),
        "parser_warnings": source.get("parser_warnings"),
    }


def public_media(media: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": media.get("id"),
        "kind": media.get("kind"),
        "download_status": media.get("download_status"),
        "download_error": media.get("download_error"),
        "original_url": media.get("original_url"),
        "mime_type": media.get("mime_type"),
        "width": media.get("width"),
        "height": media.get("height"),
        "file_size_bytes": media.get("file_size_bytes"),
    }


def public_evidence(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "field_name": item.get("field_name"),
        "value_text": item.get("value_text"),
        "source_label": item.get("source_label"),
        "source_text_snippet": item.get("source_text_snippet"),
        "confidence": item.get("confidence"),
    }


def local_media_path(media: dict[str, Any]) -> Path | None:
    local_path = media.get("local_path")
    if not local_path:
        return None
    path = Path(str(local_path))
    try:
        path.relative_to(PROJECTS_DIR)
    except ValueError:
        return None
    if not path.exists() or not path.is_file():
        return None
    return path


def image_as_jpeg_base64(path: Path, max_size: int = 1024) -> tuple[str, str]:
    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((max_size, max_size))
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=82, optimize=True)
            return base64.b64encode(out.getvalue()).decode("ascii"), "image/jpeg"
    except UnidentifiedImageError:
        data = path.read_bytes()
        suffix = path.suffix.lower()
        mime = "image/png" if suffix == ".png" else "image/webp" if suffix == ".webp" else "image/jpeg"
        return base64.b64encode(data).decode("ascii"), mime


def list_houses_tool(limit: int = 20) -> dict[str, Any]:
    houses = [public_house(house) for house in list_houses()[: max(1, min(int(limit or 20), 100))]]
    return {"houses": houses, "count": len(houses)}


def get_house_tool(house_id: str, include_evidence: bool = True, include_media: bool = True) -> dict[str, Any]:
    house = get_house(house_id)
    if not house:
        raise ValueError("Hausakte nicht gefunden")
    result: dict[str, Any] = {
        "house": public_house(house),
        "sources": [public_source(source) for source in list_sources(house_id)],
    }
    if include_media:
        result["media"] = [public_media(media) for media in list_media(house_id)]
    if include_evidence:
        result["evidence"] = [public_evidence(item) for item in list_evidence(house_id)[:80]]
    return result


def get_house_images_tool(house_id: str, limit: int = 8, max_size: int = 1024) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not get_house(house_id):
        raise ValueError("Hausakte nicht gefunden")
    limit = max(1, min(int(limit or 8), 12))
    max_size = max(256, min(int(max_size or 1024), 1600))
    images = []
    content_blocks: list[dict[str, Any]] = []
    for media in list_media(house_id):
        if media.get("kind") != "image" or media.get("download_status") != "downloaded":
            continue
        path = local_media_path(media)
        if not path:
            continue
        data, mime = image_as_jpeg_base64(path, max_size=max_size)
        images.append({"media_id": media.get("id"), "width": media.get("width"), "height": media.get("height"), "mime_type": mime})
        content_blocks.append({"type": "image", "data": data, "mimeType": mime})
        if len(images) >= limit:
            break
    return {"house_id": house_id, "images": images, "count": len(images)}, content_blocks


def list_search_profiles_tool() -> dict[str, Any]:
    profiles = []
    for profile in list_search_profiles():
        candidates = list_search_candidates(str(profile.get("id")))
        profiles.append({
            "id": profile.get("id"),
            "name": profile.get("name"),
            "source_name": profile.get("source_name"),
            "search_url": profile.get("search_url"),
            "last_run_at": profile.get("last_run_at"),
            "last_found_count": profile.get("last_found_count"),
            "candidate_count": len(candidates),
        })
    return {"profiles": profiles, "count": len(profiles)}


def get_candidates_tool(profile_id: str, limit: int = 30) -> dict[str, Any]:
    candidates = []
    for candidate in list_search_candidates(profile_id)[: max(1, min(int(limit or 30), 100))]:
        status = "imported" if candidate.get("status") == "imported" or source_url_exists(str(candidate.get("source_url"))) else candidate.get("status")
        candidates.append({
            "id": candidate.get("id"),
            "title": candidate.get("title"),
            "status": status,
            "source_url": candidate.get("source_url"),
            "price_eur": candidate.get("price_eur"),
            "living_area_m2": candidate.get("living_area_m2"),
            "plot_area_m2": candidate.get("plot_area_m2"),
            "energy_hwb": candidate.get("energy_hwb"),
            "preview_image_url": candidate.get("preview_image_url"),
            "filter_reasons": candidate.get("filter_reasons"),
        })
    return {"profile_id": profile_id, "candidates": candidates, "count": len(candidates)}


def mcp_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "list_houses",
            "description": "Liste die gespeicherten Hausakten in HausCheck.",
            "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 20}}, "additionalProperties": False},
        },
        {
            "name": "get_house",
            "description": "Lies die Details einer Hausakte inklusive Quellen, Medienmetadaten und Feldherkunft.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "house_id": {"type": "string"},
                    "include_evidence": {"type": "boolean", "default": True},
                    "include_media": {"type": "boolean", "default": True},
                },
                "required": ["house_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_house_images",
            "description": "Lade die besten lokalen Bilder einer Hausakte als Bildinhalte für die Analyse.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "house_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 8},
                    "max_size": {"type": "integer", "default": 1024},
                },
                "required": ["house_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "list_search_profiles",
            "description": "Liste gespeicherte Suchprofile und Kandidatenanzahlen.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "get_candidates",
            "description": "Lies Kandidaten eines Suchprofils mit Fakten, Status und Vorschaubild-URL.",
            "inputSchema": {
                "type": "object",
                "properties": {"profile_id": {"type": "string"}, "limit": {"type": "integer", "default": 30}},
                "required": ["profile_id"],
                "additionalProperties": False,
            },
        },
    ]


def json_text_content(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}]


def call_mcp_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    image_blocks: list[dict[str, Any]] = []
    if name == "list_houses":
        data = list_houses_tool(limit=arguments.get("limit", 20))
    elif name == "get_house":
        data = get_house_tool(
            house_id=str(arguments.get("house_id") or ""),
            include_evidence=bool(arguments.get("include_evidence", True)),
            include_media=bool(arguments.get("include_media", True)),
        )
    elif name == "get_house_images":
        data, image_blocks = get_house_images_tool(
            house_id=str(arguments.get("house_id") or ""),
            limit=int(arguments.get("limit", 8)),
            max_size=int(arguments.get("max_size", 1024)),
        )
    elif name == "list_search_profiles":
        data = list_search_profiles_tool()
    elif name == "get_candidates":
        data = get_candidates_tool(profile_id=str(arguments.get("profile_id") or ""), limit=int(arguments.get("limit", 30)))
    else:
        raise ValueError(f"Unbekanntes Tool: {name}")
    return {"content": json_text_content(data) + image_blocks, "structuredContent": data, "isError": False}


def mcp_response(request_id: Any, result: Any) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})


def mcp_error(request_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


def handle_mcp_message(message: dict[str, Any]) -> JSONResponse:
    request_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}

    if method == "initialize":
        return mcp_response(request_id, {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": "0.5.2"},
        })
    if method == "notifications/initialized":
        return mcp_response(request_id, {})
    if method == "ping":
        return mcp_response(request_id, {})
    if method == "tools/list":
        return mcp_response(request_id, {"tools": mcp_tools()})
    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        try:
            return mcp_response(request_id, call_mcp_tool(name, arguments))
        except Exception as exc:
            return mcp_response(request_id, {"content": [{"type": "text", "text": str(exc)}], "isError": True})

    return mcp_error(request_id, -32601, f"MCP-Methode nicht unterstützt: {method}")


def register_chatgpt_api(app: FastAPI) -> None:
    @app.get("/api/chatgpt/health")
    async def chatgpt_health(request: Request) -> dict[str, Any]:
        check_api_auth(request)
        return {"status": "ok", "server": SERVER_NAME, "token_configured": bool(configured_token())}

    @app.get("/api/chatgpt/houses")
    async def api_houses(request: Request, limit: int = 20) -> dict[str, Any]:
        check_api_auth(request)
        return list_houses_tool(limit=limit)

    @app.get("/api/chatgpt/houses/{house_id}")
    async def api_house(request: Request, house_id: str) -> dict[str, Any]:
        check_api_auth(request)
        try:
            return get_house_tool(house_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/chatgpt/search-profiles")
    async def api_search_profiles(request: Request) -> dict[str, Any]:
        check_api_auth(request)
        return list_search_profiles_tool()

    @app.get("/api/chatgpt/search-profiles/{profile_id}/candidates")
    async def api_candidates(request: Request, profile_id: str, limit: int = 30) -> dict[str, Any]:
        check_api_auth(request)
        return get_candidates_tool(profile_id, limit=limit)

    @app.post("/mcp")
    async def mcp_endpoint(request: Request) -> JSONResponse:
        check_api_auth(request)
        message = await request.json()
        if isinstance(message, list):
            responses = []
            for item in message:
                if isinstance(item, dict):
                    responses.append(handle_mcp_message(item).body.decode("utf-8"))
            return JSONResponse([json.loads(item) for item in responses])
        if not isinstance(message, dict):
            return mcp_error(None, -32600, "Ungültige MCP-Anfrage")
        return handle_mcp_message(message)

    @app.get("/mcp")
    async def mcp_info(request: Request) -> dict[str, Any]:
        check_api_auth(request)
        return {"server": SERVER_NAME, "transport": "streamable-http", "endpoint": "/mcp", "tools": [tool["name"] for tool in mcp_tools()]}
