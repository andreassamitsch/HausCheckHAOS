from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from app.import_patch import import_listing_to_pipeline
from app.main import run_search_profile, source_url_exists
from app.storage import connect, ensure_columns, get_search_profile, list_search_candidates, list_search_profiles, now_iso
from app.ui_helpers import score_property


OPTIONS_PATH = Path("/data/options.json")
_search_task: asyncio.Task | None = None
_cycle_lock = asyncio.Lock()


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
    return str(value).strip().lower() in {"1", "true", "yes", "on", "ja"}


def _option(name: str, default: Any) -> Any:
    env = os.environ.get(f"HAUSCHECK_{name.upper()}")
    if env is not None:
        return env
    return _load_options().get(name, default)


def search_automation_enabled() -> bool:
    return _truthy(_option("search_automation_enabled", True), True)


def scheduler_poll_seconds() -> int:
    try:
        seconds = int(float(str(_option("search_scheduler_poll_seconds", 60))))
    except Exception:
        seconds = 60
    return max(30, min(seconds, 900))


def ensure_search_automation_schema() -> None:
    with connect() as con:
        ensure_columns(
            con,
            "search_profiles",
            {
                "area_ids": "TEXT",
                "automation_mode": "TEXT NOT NULL DEFAULT 'manual'",
                "run_interval_minutes": "INTEGER NOT NULL DEFAULT 60",
                "auto_import_enabled": "INTEGER NOT NULL DEFAULT 0",
                "max_results": "INTEGER NOT NULL DEFAULT 80",
                "last_run_status": "TEXT",
                "last_error": "TEXT",
                "auto_import_min_score": "INTEGER NOT NULL DEFAULT 68",
                "auto_import_limit_per_run": "INTEGER NOT NULL DEFAULT 2",
                "last_auto_import_count": "INTEGER NOT NULL DEFAULT 0",
                "last_auto_import_at": "TEXT",
            },
        )
        ensure_columns(
            con,
            "search_candidates",
            {
                "provider": "TEXT NOT NULL DEFAULT 'willhaben.at'",
                "external_id": "TEXT",
                "canonical_url": "TEXT",
                "content_hash": "TEXT",
                "last_changed_at": "TEXT",
                "offline_at": "TEXT",
                "decision": "TEXT",
                "raw_data_json": "TEXT",
                "change_count": "INTEGER NOT NULL DEFAULT 0",
                "auto_import_attempted_at": "TEXT",
                "auto_import_error": "TEXT",
            },
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_search_candidates_external ON search_candidates(provider, external_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_search_candidates_status ON search_candidates(profile_id, status)")
        con.commit()


def update_profile_automation(profile_id: str, data: dict[str, Any]) -> None:
    ensure_search_automation_schema()
    allowed = {
        "enabled",
        "area_ids",
        "automation_mode",
        "run_interval_minutes",
        "auto_import_enabled",
        "max_results",
        "last_run_status",
        "last_error",
        "last_run_at",
        "auto_import_min_score",
        "auto_import_limit_per_run",
        "last_auto_import_count",
        "last_auto_import_at",
    }
    fields = {key: value for key, value in data.items() if key in allowed}
    if not fields:
        return
    fields["updated_at"] = now_iso()
    sql = ", ".join(f"{key} = ?" for key in fields)
    with connect() as con:
        con.execute(f"UPDATE search_profiles SET {sql} WHERE id = ?", list(fields.values()) + [profile_id])
        con.commit()


def _external_id(url: str) -> str | None:
    match = re.search(r"-(\d{7,})(?:$|[/?#])", url or "")
    return match.group(1) if match else None


def _canonical_url(url: str) -> str:
    return str(url or "").split("?", 1)[0].split("#", 1)[0].rstrip("/")


def _candidate_hash(candidate: dict[str, Any]) -> str:
    payload = {
        "title": candidate.get("title"),
        "price_eur": candidate.get("price_eur"),
        "living_area_m2": candidate.get("living_area_m2"),
        "plot_area_m2": candidate.get("plot_area_m2"),
        "energy_hwb": candidate.get("energy_hwb"),
        "preview_image_url": candidate.get("preview_image_url"),
        "status": candidate.get("status"),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def sync_candidate_metadata(profile_id: str) -> None:
    ensure_search_automation_schema()
    timestamp = now_iso()
    candidates = list_search_candidates(profile_id)
    with connect() as con:
        for candidate in candidates:
            source_url = str(candidate.get("source_url") or "")
            new_hash = _candidate_hash(candidate)
            old_hash = str(candidate.get("content_hash") or "")
            changed = bool(old_hash and old_hash != new_hash)
            raw_data = {
                "title": candidate.get("title"),
                "price_eur": candidate.get("price_eur"),
                "living_area_m2": candidate.get("living_area_m2"),
                "plot_area_m2": candidate.get("plot_area_m2"),
                "energy_hwb": candidate.get("energy_hwb"),
                "preview_image_url": candidate.get("preview_image_url"),
                "filter_reasons": candidate.get("filter_reasons"),
            }
            con.execute(
                """
                UPDATE search_candidates
                SET provider = 'willhaben.at',
                    external_id = COALESCE(external_id, ?),
                    canonical_url = ?,
                    content_hash = ?,
                    last_changed_at = CASE
                        WHEN last_changed_at IS NULL OR ? = 1 THEN ?
                        ELSE last_changed_at
                    END,
                    change_count = change_count + ?,
                    decision = COALESCE(decision, status),
                    raw_data_json = ?
                WHERE id = ?
                """,
                (
                    _external_id(source_url),
                    _canonical_url(source_url),
                    new_hash,
                    1 if changed else 0,
                    timestamp,
                    1 if changed else 0,
                    json.dumps(raw_data, ensure_ascii=False),
                    candidate["id"],
                ),
            )
        con.commit()


def _parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def profile_is_due(profile: dict[str, Any], now: datetime | None = None) -> bool:
    if not bool(int(profile.get("enabled") or 0)):
        return False
    mode = str(profile.get("automation_mode") or "manual")
    if mode not in {"review", "automatic"}:
        return False
    try:
        interval = max(15, min(int(profile.get("run_interval_minutes") or 60), 1440))
    except Exception:
        interval = 60
    last_run = _parse_datetime(profile.get("last_run_at"))
    if last_run is None:
        return True
    current = now or datetime.now(timezone.utc)
    return (current - last_run).total_seconds() >= interval * 60


def _eligible_candidates(profile: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    try:
        threshold = max(0, min(int(profile.get("auto_import_min_score") or 68), 100))
    except Exception:
        threshold = 68
    result: list[tuple[int, dict[str, Any]]] = []
    for candidate in list_search_candidates(str(profile["id"])):
        if str(candidate.get("status") or "new") != "new":
            continue
        if candidate.get("imported_house_id"):
            continue
        source_url = str(candidate.get("source_url") or "")
        if not source_url or source_url_exists(source_url):
            continue
        score = int(score_property(candidate, "new").get("score") or 0)
        if score >= threshold:
            result.append((score, candidate))
    result.sort(key=lambda pair: (pair[0], str(pair[1].get("first_seen_at") or "")), reverse=True)
    return result


async def _auto_import_candidates(profile: dict[str, Any]) -> dict[str, Any]:
    mode = str(profile.get("automation_mode") or "manual")
    auto_enabled = bool(int(profile.get("auto_import_enabled") or 0)) or mode == "automatic"
    if not auto_enabled:
        return {"imported": [], "errors": []}

    try:
        limit = max(1, min(int(profile.get("auto_import_limit_per_run") or 2), 10))
    except Exception:
        limit = 2

    imported: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for score, candidate in _eligible_candidates(profile)[:limit]:
        candidate_id = str(candidate.get("id") or "")
        source_url = str(candidate.get("source_url") or "")
        attempted_at = now_iso()
        try:
            result = await import_listing_to_pipeline(source_url, str(candidate.get("preview_image_url") or "") or None)
            house = result.get("house") or {}
            with connect() as con:
                con.execute(
                    """
                    UPDATE search_candidates
                    SET decision = 'auto_imported', auto_import_attempted_at = ?, auto_import_error = NULL
                    WHERE id = ?
                    """,
                    (attempted_at, candidate_id),
                )
                con.commit()
            imported.append({"candidate_id": candidate_id, "house_id": house.get("id"), "score": score})
        except Exception as exc:
            error_text = str(exc)[:1000]
            with connect() as con:
                con.execute(
                    """
                    UPDATE search_candidates
                    SET decision = 'auto_import_error', auto_import_attempted_at = ?, auto_import_error = ?
                    WHERE id = ?
                    """,
                    (attempted_at, error_text, candidate_id),
                )
                con.commit()
            errors.append({"candidate_id": candidate_id, "url": source_url, "error": error_text})
    return {"imported": imported, "errors": errors}


async def execute_profile_cycle(profile_id: str, force: bool = False) -> dict[str, Any]:
    ensure_search_automation_schema()
    async with _cycle_lock:
        profile = get_search_profile(profile_id)
        if not profile:
            raise ValueError("Suchprofil nicht gefunden")
        if not force and not profile_is_due(profile):
            return {"profile_id": profile_id, "skipped": True, "reason": "noch nicht fällig"}

        update_profile_automation(profile_id, {"last_run_status": "läuft", "last_error": None})
        try:
            found = await run_search_profile(profile_id, int(profile.get("max_results") or 80))
            sync_candidate_metadata(profile_id)
            refreshed = get_search_profile(profile_id) or profile
            auto_result = await _auto_import_candidates(refreshed)
            imported_count = len(auto_result["imported"])
            update_profile_automation(
                profile_id,
                {
                    "last_run_status": f"erfolgreich · {found} Treffer · {imported_count} automatisch importiert",
                    "last_error": None if not auto_result["errors"] else json.dumps(auto_result["errors"], ensure_ascii=False)[:1000],
                    "last_auto_import_count": imported_count,
                    "last_auto_import_at": now_iso() if imported_count else refreshed.get("last_auto_import_at"),
                },
            )
            return {
                "profile_id": profile_id,
                "found": found,
                "imported": auto_result["imported"],
                "errors": auto_result["errors"],
            }
        except Exception as exc:
            update_profile_automation(
                profile_id,
                {"last_run_status": "Fehler", "last_error": str(exc)[:1000], "last_run_at": now_iso()},
            )
            raise


async def _search_scheduler_loop() -> None:
    await asyncio.sleep(30)
    while True:
        try:
            if search_automation_enabled():
                now = datetime.now(timezone.utc)
                for profile in list_search_profiles():
                    if profile_is_due(profile, now):
                        try:
                            result = await execute_profile_cycle(str(profile["id"]))
                            print(f"HausCheck Suche: {result}", flush=True)
                        except Exception as exc:
                            print(f"HausCheck Suche fehlgeschlagen für {profile.get('id')}: {exc}", flush=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"HausCheck Such-Scheduler Fehler: {exc}", flush=True)
        await asyncio.sleep(scheduler_poll_seconds())


def register_search_automation(app: FastAPI) -> None:
    ensure_search_automation_schema()

    @app.on_event("startup")
    async def start_search_scheduler() -> None:
        global _search_task
        if _search_task is None or _search_task.done():
            _search_task = asyncio.create_task(_search_scheduler_loop())
            print("HausCheck Such-Scheduler gestartet", flush=True)

    @app.on_event("shutdown")
    async def stop_search_scheduler() -> None:
        global _search_task
        if _search_task and not _search_task.done():
            _search_task.cancel()
        _search_task = None
