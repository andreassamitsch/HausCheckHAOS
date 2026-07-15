from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
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


def _analysis_path(house_id: str) -> Path:
    return project_dir(house_id) / "analysis" / "hauscheck_analysis.json"


def _parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    # Ein reines Datum ist für einen sekundengenauen Frischevergleich ungeeignet.
    if len(text) == 10:
        try:
            date.fromisoformat(text)
        except ValueError:
            pass
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _analysis_metadata(house_id: str) -> dict[str, Any]:
    path = _analysis_path(house_id)
    if not path.exists():
        return {"exists": False, "analysis_date": None, "file_updated_at": None}

    analysis_date: object = None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            analysis_date = payload.get("analysis_date")
    except Exception:
        analysis_date = None

    try:
        file_updated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        file_updated_at = None
    return {
        "exists": True,
        "analysis_date": analysis_date,
        "file_updated_at": file_updated_at,
    }


def _analysis_is_current(status: dict[str, Any], metadata: dict[str, Any]) -> bool:
    if not metadata.get("exists"):
        return False

    stage = str(status.get("stage") or "created")
    exported_at = _parse_datetime(status.get("exported_at"))
    imported_at = _parse_datetime(status.get("analysis_imported_at"))
    generated_at = _parse_datetime(metadata.get("analysis_date"))
    file_updated_at = _parse_datetime(metadata.get("file_updated_at"))

    # Sobald ein neues Paket exportiert wird, bleibt die vorhandene Analyse nur
    # noch eine historische Vorschau – sie darf den neuen Lauf nicht abschließen.
    if stage in {"exporting", "waiting_analysis"}:
        return False

    if exported_at is None:
        return True

    # Ein Import muss nach dem jüngsten Export erfolgt sein. Diese Prüfung
    # repariert auch bereits fälschlich auf "completed" gesetzte Altbestände.
    if imported_at is not None and imported_at < exported_at:
        return False

    # Ein zurückgeliefertes Ergebnis mit altem Analysezeitpunkt gehört nicht zum
    # jüngsten Paket. Fünf Minuten Toleranz decken kleine Uhrabweichungen ab.
    if generated_at is not None and generated_at < exported_at - timedelta(minutes=5):
        return False

    if imported_at is not None:
        return imported_at >= exported_at
    if file_updated_at is not None:
        return file_updated_at >= exported_at
    return stage == "completed"


def get_pipeline_status(house_id: str) -> dict[str, Any]:
    _ensure_row(house_id)
    sources = list_sources(house_id)
    media = list_media(house_id)
    downloaded = len([item for item in media if item.get("download_status") == "downloaded"])
    pending = len([item for item in media if item.get("download_status") == "pending"])
    failed = len([item for item in media if item.get("download_status") == "failed"])
    metadata = _analysis_metadata(house_id)

    with connect() as con:
        row = con.execute("SELECT * FROM house_pipeline_status WHERE house_id = ?", (house_id,)).fetchone()
    status = row_to_dict(row) or {}
    analysis_current = _analysis_is_current(status, metadata)

    # Bestehende Hausakten ohne Ereignishistorie werden nur dann aus dem realen
    # Datenstand als abgeschlossen eingeordnet, wenn kein neuer Export aussteht.
    if analysis_current and status.get("stage") != "completed":
        status = set_pipeline_stage(
            house_id,
            "completed",
            "ok",
            "ChatGPT-Analyse wurde importiert.",
            add_event=False,
        )
        analysis_current = _analysis_is_current(status, metadata)
    elif sources and not status.get("listing_imported_at"):
        timestamp = now_iso()
        with connect() as con:
            con.execute(
                "UPDATE house_pipeline_status SET listing_imported_at = ?, updated_at = ? WHERE house_id = ?",
                (timestamp, timestamp, house_id),
            )
            con.commit()
        with connect() as con:
            row = con.execute("SELECT * FROM house_pipeline_status WHERE house_id = ?", (house_id,)).fetchone()
        status = row_to_dict(row) or status
        analysis_current = _analysis_is_current(status, metadata)

    analysis_exists = bool(metadata.get("exists"))
    analysis_stale = analysis_exists and not analysis_current
    stored_stage = str(status.get("stage") or "created")
    if analysis_stale and status.get("exported_at") and stored_stage != "error":
        # Alte Versionen konnten einen noch laufenden Export wegen der vorhandenen
        # Altanalyse fälschlich wieder auf completed setzen. Für die Anzeige und
        # Zählung gilt der Lauf weiterhin als ausstehend; die Zeitstempel bleiben erhalten.
        status["stored_stage"] = stored_stage
        status["stage"] = "waiting_analysis"
        status["state"] = "pending"
        status["message"] = "Neue ChatGPT-Analyse ist ausstehend; die vorige Analyse bleibt vorläufig sichtbar."

    status.update(
        {
            "source_count": len(sources),
            "media_count": len(media),
            "downloaded_count": downloaded,
            "pending_count": pending,
            "failed_count": failed,
            "analysis_exists": analysis_exists,
            "analysis_current": analysis_current,
            "analysis_stale": analysis_stale,
            "analysis_date": metadata.get("analysis_date"),
            "analysis_file_updated_at": metadata.get("file_updated_at"),
            "stage_label": STAGE_LABELS.get(str(status.get("stage") or "created"), "Unbekannt"),
        }
    )
    return status


def pipeline_counts() -> dict[str, int]:
    ensure_pipeline_schema()
    with connect() as con:
        rows = con.execute("SELECT house_id FROM house_pipeline_status").fetchall()

    waiting = completed = errors = 0
    for row in rows:
        status = get_pipeline_status(str(row["house_id"]))
        stage = str(status.get("stage") or "created")
        state = str(status.get("state") or "pending")
        if state == "error" or stage == "error":
            errors += 1
        elif status.get("analysis_current"):
            completed += 1
        elif stage in {"exporting", "waiting_analysis"} or status.get("analysis_stale"):
            waiting += 1
    return {"waiting": waiting, "completed": completed, "errors": errors}
