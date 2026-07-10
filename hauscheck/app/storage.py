from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.environ.get("HAUSCHECK_DATA_DIR", "/share/hauscheck"))
DB_PATH = DATA_DIR / "hauscheck.db"
PROJECTS_DIR = DATA_DIR / "projects"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_storage() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS houses (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'new',
                location_text TEXT,
                address_status TEXT NOT NULL DEFAULT 'unknown',
                price_eur INTEGER,
                living_area_m2 REAL,
                plot_area_m2 REAL,
                rooms REAL,
                year_built INTEGER,
                heating TEXT,
                energy_hwb REAL,
                energy_fgee REAL,
                energy_class_hwb TEXT,
                energy_class_fgee TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS listing_sources (
                id TEXT PRIMARY KEY,
                house_id TEXT NOT NULL,
                source_name TEXT NOT NULL,
                source_url TEXT NOT NULL,
                external_id TEXT,
                description TEXT,
                raw_html_path TEXT,
                parser_status TEXT,
                parser_warnings TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(house_id) REFERENCES houses(id)
            );

            CREATE TABLE IF NOT EXISTS media_assets (
                id TEXT PRIMARY KEY,
                house_id TEXT NOT NULL,
                source_id TEXT,
                kind TEXT NOT NULL,
                original_url TEXT,
                local_path TEXT,
                mime_type TEXT,
                download_status TEXT NOT NULL DEFAULT 'pending',
                download_error TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(house_id) REFERENCES houses(id)
            );

            CREATE TABLE IF NOT EXISTS field_evidence (
                id TEXT PRIMARY KEY,
                house_id TEXT NOT NULL,
                source_id TEXT,
                field_name TEXT NOT NULL,
                value_text TEXT,
                source_label TEXT,
                source_text_snippet TEXT,
                confidence TEXT NOT NULL DEFAULT 'unknown',
                created_at TEXT NOT NULL,
                FOREIGN KEY(house_id) REFERENCES houses(id)
            );
            """
        )
        con.commit()


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def project_dir(house_id: str) -> Path:
    base = PROJECTS_DIR / house_id
    for sub in ["html", "images", "pdfs", "videos", "screenshots", "exports", "analysis"]:
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


def create_house(data: dict[str, Any]) -> dict[str, Any]:
    house_id = str(uuid.uuid4())[:8]
    timestamp = now_iso()
    project_dir(house_id)
    with connect() as con:
        con.execute(
            """
            INSERT INTO houses (
                id, title, status, location_text, address_status, price_eur,
                living_area_m2, plot_area_m2, rooms, year_built, heating,
                energy_hwb, energy_fgee, energy_class_hwb, energy_class_fgee,
                notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                house_id,
                data.get("title") or "Unbenanntes Objekt",
                data.get("status") or "new",
                data.get("location_text"),
                data.get("address_status") or "unknown",
                data.get("price_eur"),
                data.get("living_area_m2"),
                data.get("plot_area_m2"),
                data.get("rooms"),
                data.get("year_built"),
                data.get("heating"),
                data.get("energy_hwb"),
                data.get("energy_fgee"),
                data.get("energy_class_hwb"),
                data.get("energy_class_fgee"),
                data.get("notes"),
                timestamp,
                timestamp,
            ),
        )
        con.commit()
    return get_house(house_id) or {}


def update_house(house_id: str, data: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "title", "status", "location_text", "address_status", "price_eur",
        "living_area_m2", "plot_area_m2", "rooms", "year_built", "heating",
        "energy_hwb", "energy_fgee", "energy_class_hwb", "energy_class_fgee", "notes"
    }
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return get_house(house_id) or {}
    fields["updated_at"] = now_iso()
    sql = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [house_id]
    with connect() as con:
        con.execute(f"UPDATE houses SET {sql} WHERE id = ?", values)
        con.commit()
    return get_house(house_id) or {}


def list_houses() -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute("SELECT * FROM houses ORDER BY created_at DESC").fetchall()
    return [row_to_dict(row) or {} for row in rows]


def get_house(house_id: str) -> dict[str, Any] | None:
    with connect() as con:
        row = con.execute("SELECT * FROM houses WHERE id = ?", (house_id,)).fetchone()
    return row_to_dict(row)


def create_source(house_id: str, data: dict[str, Any]) -> dict[str, Any]:
    source_id = str(uuid.uuid4())[:8]
    timestamp = now_iso()
    with connect() as con:
        con.execute(
            """
            INSERT INTO listing_sources (
                id, house_id, source_name, source_url, external_id, description,
                raw_html_path, parser_status, parser_warnings, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_id,
                house_id,
                data.get("source_name") or "unknown",
                data.get("source_url") or "",
                data.get("external_id"),
                data.get("description"),
                data.get("raw_html_path"),
                data.get("parser_status") or "partial",
                json.dumps(data.get("parser_warnings") or [], ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )
        con.commit()
    return get_source(source_id) or {}


def get_source(source_id: str) -> dict[str, Any] | None:
    with connect() as con:
        row = con.execute("SELECT * FROM listing_sources WHERE id = ?", (source_id,)).fetchone()
    return row_to_dict(row)


def list_sources(house_id: str) -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute("SELECT * FROM listing_sources WHERE house_id = ? ORDER BY created_at DESC", (house_id,)).fetchall()
    return [row_to_dict(row) or {} for row in rows]


def add_media(house_id: str, data: dict[str, Any]) -> dict[str, Any]:
    media_id = str(uuid.uuid4())[:8]
    timestamp = now_iso()
    with connect() as con:
        con.execute(
            """
            INSERT INTO media_assets (
                id, house_id, source_id, kind, original_url, local_path, mime_type,
                download_status, download_error, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                media_id,
                house_id,
                data.get("source_id"),
                data.get("kind") or "image",
                data.get("original_url"),
                data.get("local_path"),
                data.get("mime_type"),
                data.get("download_status") or "pending",
                data.get("download_error"),
                timestamp,
            ),
        )
        con.commit()
    return media_id and get_media(media_id) or {}


def update_media(media_id: str, data: dict[str, Any]) -> dict[str, Any]:
    allowed = {"local_path", "mime_type", "download_status", "download_error"}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return get_media(media_id) or {}
    sql = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [media_id]
    with connect() as con:
        con.execute(f"UPDATE media_assets SET {sql} WHERE id = ?", values)
        con.commit()
    return get_media(media_id) or {}


def get_media(media_id: str) -> dict[str, Any] | None:
    with connect() as con:
        row = con.execute("SELECT * FROM media_assets WHERE id = ?", (media_id,)).fetchone()
    return row_to_dict(row)


def list_media(house_id: str) -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute("SELECT * FROM media_assets WHERE house_id = ? ORDER BY created_at DESC", (house_id,)).fetchall()
    return [row_to_dict(row) or {} for row in rows]


def add_evidence(house_id: str, source_id: str | None, items: list[dict[str, Any]]) -> None:
    timestamp = now_iso()
    with connect() as con:
        for item in items:
            con.execute(
                """
                INSERT INTO field_evidence (
                    id, house_id, source_id, field_name, value_text, source_label,
                    source_text_snippet, confidence, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4())[:8],
                    house_id,
                    source_id,
                    item.get("field_name") or item.get("field") or "unknown",
                    str(item.get("value")) if item.get("value") is not None else None,
                    item.get("source_label"),
                    item.get("source_text_snippet"),
                    item.get("confidence") or "unknown",
                    timestamp,
                ),
            )
        con.commit()


def list_evidence(house_id: str) -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute("SELECT * FROM field_evidence WHERE house_id = ? ORDER BY created_at DESC", (house_id,)).fetchall()
    return [row_to_dict(row) or {} for row in rows]
