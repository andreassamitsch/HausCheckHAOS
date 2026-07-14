from __future__ import annotations

from typing import Any

from fastapi import FastAPI

import app.immoscout_dynamic_search as dynamic
import app.immoscout_support as support
import app.main as main
from app.storage import connect, ensure_columns, get_search_profile


_PATCHED = False
_ORIGINAL_CREATE_SEARCH_PROFILE = support.create_search_profile
_ORIGINAL_VALIDATE = dynamic.validate_search_profile_url_dynamic
_ORIGINAL_PARSE_SEARCH_AREAS = dynamic.parse_search_areas


def parse_search_areas_any(value: object) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        value = ",".join(str(item) for item in value)
    return _ORIGINAL_PARSE_SEARCH_AREAS(value)


def ensure_dynamic_mode_schema() -> None:
    with connect() as con:
        ensure_columns(
            con,
            "search_profiles",
            {"search_url_mode": "TEXT NOT NULL DEFAULT 'automatic'"},
        )
        rows = con.execute(
            "SELECT id, source_name, search_url, search_url_mode FROM search_profiles"
        ).fetchall()
        for row in rows:
            provider = str(row["source_name"] or support.WILLHABEN_SOURCE)
            urls = dynamic._split_urls(row["search_url"])
            inferred = "custom" if urls and any(not dynamic._is_auto_url(provider, url) for url in urls) else "automatic"
            current = str(row["search_url_mode"] or "").strip().lower()
            if current not in {"automatic", "custom"} or current == "automatic":
                con.execute(
                    "UPDATE search_profiles SET search_url_mode = ? WHERE id = ?",
                    (inferred, row["id"]),
                )
        con.commit()


def validate_with_mode(
    source_name: str,
    search_url: str,
    profile_data: dict[str, Any],
    area_ids: str | None,
) -> tuple[str, str]:
    provider, resolved = _ORIGINAL_VALIDATE(source_name, search_url, profile_data, area_ids)
    profile_data["search_url_mode"] = "custom" if dynamic._split_urls(search_url) else "automatic"
    return provider, resolved


def create_search_profile_with_mode(data: dict[str, Any]) -> dict[str, Any]:
    profile = _ORIGINAL_CREATE_SEARCH_PROFILE(data)
    mode = str(data.get("search_url_mode") or "automatic")
    with connect() as con:
        con.execute(
            "UPDATE search_profiles SET search_url_mode = ? WHERE id = ?",
            (mode if mode in {"automatic", "custom"} else "automatic", profile["id"]),
        )
        con.commit()
    return get_search_profile(str(profile["id"])) or profile


def custom_search_text_mode(profile: dict[str, Any]) -> str:
    if str(profile.get("search_url_mode") or "automatic") != "custom":
        return ""
    return "\n".join(dynamic._split_urls(profile.get("search_url")))


def resolve_search_urls_mode(profile: dict[str, Any]) -> list[str]:
    provider = str(profile.get("source_name") or support.WILLHABEN_SOURCE)
    urls = dynamic._split_urls(profile.get("search_url"))
    if str(profile.get("search_url_mode") or "automatic") == "custom" and urls:
        return urls
    areas = dynamic._areas_from_profile(profile)
    if provider == support.IMMOSCOUT_SOURCE:
        return dynamic.build_immoscout_auto_urls(profile, areas)
    if provider == support.WILLHABEN_SOURCE:
        return main.build_willhaben_auto_urls(profile, areas)
    return dynamic._ORIGINAL_RESOLVE_SEARCH_URLS(profile)


def resolve_search_url_mode(profile: dict[str, Any]) -> str:
    return "\n".join(resolve_search_urls_mode(profile))


def register_immoscout_dynamic_mode(app: FastAPI) -> None:
    global _PATCHED
    if _PATCHED:
        return

    ensure_dynamic_mode_schema()
    dynamic.parse_search_areas = parse_search_areas_any
    support.create_search_profile = create_search_profile_with_mode
    support._validate_search_profile_url = validate_with_mode
    dynamic.validate_search_profile_url_dynamic = validate_with_mode
    dynamic._custom_search_text = custom_search_text_mode
    dynamic.resolve_search_urls_dynamic = resolve_search_urls_mode
    dynamic.resolve_search_url_dynamic = resolve_search_url_mode
    main.resolve_search_urls = resolve_search_urls_mode
    main.resolve_search_url = resolve_search_url_mode
    _PATCHED = True
