from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from app.storage import connect, list_media, list_sources, now_iso, project_dir, row_to_dict


STAGE_LABELS = {
    "created": "Hausakte angelegt",
    "listing_imported": "Inserat erfasst",
    "media_loading": "Medien werden geladen",
    "media_ready": "Medien geladen",
    "exporting": "Analysepaket wird bereitgestellt",
    "waiting_analysis": "ChatGPT-Analyse ausstehend",
    "completed": "Analyse importiert",
    "error": "Fehler",
}

TIMESTAMP_COLUMNS = {
    "created": "created_at",
    "listing_imported": "listing_imported_at",
    "media_ready": "media_ready_at",
    "waiting_analysis": "exported_at",
    "completed": "analysis_imported_at",
}


def ensure_pipeline_schema() -> None:
    with connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS house_pipeline_status (
                house_id TEXT PRIMARY KEY,
                stage TEXT NOT NULL DEFAULT 'created',
                state TEXT NOT NULL DEFAULT 'pending',
                message TEXT,
                last_error TEXT,
                created_at TEXT,
                listing_imported_at TEXT,
                media_ready_at TEXT,
                exported_at TEXT,
                analysis_imported_at TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS house_pipeline_events (
                id TEXT PRIMARY KEY,
                house_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                state TEXT NOT NULL,
                message TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_pipeline_events_house
            ON house_pipeline_events(house_id, created_at DESC);
            """
        )
        con.commit()


def _ensure_row(house_id: str) -> None:
    ensure_pipeline_schema()
    timestamp = now_iso()
    with connect() as con:
        con.execute(
            """
            INSERT OR IGNORE INTO house_pipeline_status (
                house_id, stage, state, message, created_at, updated_at
            ) VALUES (?, 'created', 'pending', 'Hausakte wurde angelegt.', ?, ?)
            """,
            (house_id, timestamp, timestamp),
        )
        con.commit()


def set_pipeline_stage(
    house_id: str,
    stage: str,
    state: str = "ok",
    message: str | None = None,
    error: str | None = None,
    add_event: bool = True,
) -> dict[str, Any]:
    _ensure_row(house_id)
    timestamp = now_iso()
    normalized_stage = stage if stage in STAGE_LABELS else "error"
    normalized_state = state if state in {"pending", "running", "ok", "error"} else "pending"

    fields: dict[str, Any] = {
        "stage": normalized_stage,
        "state": normalized_state,
        "message": message or STAGE_LABELS.get(normalized_stage, normalized_stage),
        "updated_at": timestamp,
    }
    if normalized_state == "error" or error:
        fields["last_error"] = (error or message or "Unbekannter Fehler")[:1000]
    else:
        fields["last_error"] = None

    timestamp_column = TIMESTAMP_COLUMNS.get(normalized_stage)
    if timestamp_column:
        fields[timestamp_column] = timestamp

    sql = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [house_id]
    with connect() as con:
        con.execute(f"UPDATE house_pipeline_status SET {sql} WHERE house_id = ?", values)
        if add_event:
            con.execute(
                """
                INSERT INTO house_pipeline_events (id, house_id, stage, state, message, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4())[:8],
                    house_id,
                    normalized_stage,
                    normalized_state,
                    fields["message"],
                    timestamp,
                ),
            )
        con.commit()
        row = con.execute("SELECT * FROM house_pipeline_status WHERE house_id = ?", (house_id,)).fetchone()
    return row_to_dict(row) or {}


def list_pipeline_events(house_id: str, limit: int = 12) -> list[dict[str, Any]]:
    ensure_pipeline_schema()
    with connect() as con:
        rows = con.execute(
            """
            SELECT * FROM house_pipeline_events
            WHERE house_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (house_id, max(1, min(limit, 100))),
        ).fetchall()
    return [row_to_dict(row) or {} for row in rows]


def _analysis_exists(house_id: str) -> bool:
    return (project_dir(house_id) / "analysis" / "hauscheck_analysis.json").exists()


def get_pipeline_status(house_id: str) -> dict[str, Any]:
    _ensure_row(house_id)
    sources = list_sources(house_id)
    media = list_media(house_id)
    downloaded = len([item for item in media if item.get("download_status") == "downloaded"])
    pending = len([item for item in media if item.get("download_status") == "pending"])
    failed = len([item for item in media if item.get("download_status") == "failed"])
    analysis_exists = _analysis_exists(house_id)

    with connect() as con:
        row = con.execute("SELECT * FROM house_pipeline_status WHERE house_id = ?", (house_id,)).fetchone()
    status = row_to_dict(row) or {}

    # Bestehende Hausakten ohne Ereignishistorie werden aus dem realen Datenstand eingeordnet.
    if analysis_exists and status.get("stage") != "completed":
        status = set_pipeline_stage(
            house_id,
            "completed",
            "ok",
            "ChatGPT-Analyse wurde importiert.",
            add_event=False,
        )
    elif sources and not status.get("listing_imported_at"):
        with connect() as con:
            con.execute(
                "UPDATE house_pipeline_status SET listing_imported_at = ?, updated_at = ? WHERE house_id = ?",
                (now_iso(), now_iso(), house_id),
            )
            con.commit()
        with connect() as con:
            row = con.execute("SELECT * FROM house_pipeline_status WHERE house_id = ?", (house_id,)).fetchone()
        status = row_to_dict(row) or status

    status.update(
        {
            "source_count": len(sources),
            "media_count": len(media),
            "downloaded_count": downloaded,
            "pending_count": pending,
            "failed_count": failed,
            "analysis_exists": analysis_exists,
            "stage_label": STAGE_LABELS.get(str(status.get("stage") or "created"), "Unbekannt"),
        }
    )
    return status


def pipeline_counts() -> dict[str, int]:
    ensure_pipeline_schema()
    with connect() as con:
        rows = con.execute("SELECT stage, COUNT(*) AS count FROM house_pipeline_status GROUP BY stage").fetchall()
    counts = {str(row["stage"]): int(row["count"]) for row in rows}
    return {
        "waiting": counts.get("waiting_analysis", 0) + counts.get("exporting", 0),
        "completed": counts.get("completed", 0),
        "errors": counts.get("error", 0),
    }
