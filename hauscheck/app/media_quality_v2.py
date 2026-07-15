from __future__ import annotations

import hashlib
import io
import json
import math
import re
import uuid
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from PIL import Image, ImageOps, UnidentifiedImageError

from app.storage import PROJECTS_DIR, connect, ensure_columns, list_houses, now_iso


DEDUPE_VERSION = 2
AI_IMAGE_MAX_COUNT = 80
AI_IMAGE_BUDGET_BYTES = 32 * 1024 * 1024
AI_IMAGE_MAX_SIZE = 1400
AI_IMAGE_QUALITY = 82

_PATCHED = False
_ORIGINAL_ADD_MEDIA: Callable[..., dict[str, Any]] | None = None
_ORIGINAL_QUEUE_MEDIA: Callable[..., Any] | None = None
_ORIGINAL_DOWNLOAD: Callable[..., Awaitable[None]] | None = None
_ORIGINAL_CREATE_ZIP: Callable[[str], Path] | None = None
_ORIGINAL_README: Callable[[str], str] | None = None
_ORIGINAL_SCHEMA: Callable[[str], dict[str, Any]] | None = None
_LAST_SELECTION: dict[str, dict[str, Any]] = {}

_RESAMPLE = getattr(Image, "Resampling", Image).LANCZOS


def ensure_media_quality_schema() -> None:
    with connect() as con:
        ensure_columns(
            con,
            "media_assets",
            {
                "source_order": "INTEGER",
                "display_order": "INTEGER",
                "perceptual_hash": "TEXT",
                "average_hash": "TEXT",
                "center_hash": "TEXT",
                "visual_signature": "TEXT",
                "quality_score": "REAL",
                "dedupe_version": "INTEGER NOT NULL DEFAULT 0",
            },
        )
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS media_source_positions (
                house_id TEXT NOT NULL,
                media_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                original_url TEXT NOT NULL,
                source_order INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (house_id, source_id, original_url)
            );

            CREATE INDEX IF NOT EXISTS idx_media_source_positions_media
                ON media_source_positions(house_id, media_id);

            CREATE TABLE IF NOT EXISTS media_cleanup_events (
                id TEXT PRIMARY KEY,
                house_id TEXT NOT NULL,
                removed_media_id TEXT NOT NULL,
                kept_media_id TEXT,
                method TEXT NOT NULL,
                details_json TEXT,
                removed_path TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_media_cleanup_events_house
                ON media_cleanup_events(house_id, created_at DESC);

            DROP TRIGGER IF EXISTS trg_media_source_order_v2;
            CREATE TRIGGER trg_media_source_order_v2
            AFTER INSERT ON media_assets
            WHEN NEW.source_order IS NULL
            BEGIN
                UPDATE media_assets
                SET source_order = (
                    SELECT COALESCE(MAX(COALESCE(source_order, -1)), -1) + 1
                    FROM media_assets
                    WHERE house_id = NEW.house_id
                      AND kind = NEW.kind
                      AND COALESCE(source_id, '') = COALESCE(NEW.source_id, '')
                      AND id <> NEW.id
                )
                WHERE id = NEW.id;
            END;
            """
        )

        rows = con.execute(
            """
            SELECT id, house_id, source_id, kind, original_url, source_order, created_at
            FROM media_assets
            ORDER BY house_id, COALESCE(source_id, ''), kind, created_at, id
            """
        ).fetchall()
        counters: dict[tuple[str, str, str], int] = defaultdict(int)
        for row in rows:
            key = (str(row["house_id"]), str(row["source_id"] or ""), str(row["kind"] or ""))
            order = row["source_order"]
            if order is None:
                order = counters[key]
                con.execute("UPDATE media_assets SET source_order = ? WHERE id = ?", (order, row["id"]))
            counters[key] = max(counters[key], int(order or 0) + 1)
            if row["kind"] == "image" and row["source_id"] and row["original_url"]:
                con.execute(
                    """
                    INSERT INTO media_source_positions (
                        house_id, media_id, source_id, original_url, source_order, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(house_id, source_id, original_url) DO UPDATE SET
                        media_id = excluded.media_id,
                        source_order = excluded.source_order,
                        updated_at = excluded.updated_at
                    """,
                    (
                        row["house_id"],
                        row["id"],
                        row["source_id"],
                        row["original_url"],
                        int(order or 0),
                        row["created_at"] or now_iso(),
                        now_iso(),
                    ),
                )
        con.commit()


def _next_source_order(house_id: str, source_id: str) -> int:
    with connect() as con:
        row = con.execute(
            """
            SELECT MAX(source_order)
            FROM media_source_positions
            WHERE house_id = ? AND source_id = ?
            """,
            (house_id, source_id),
        ).fetchone()
    return (int(row[0]) + 1) if row and row[0] is not None else 0


def _record_source_position(
    house_id: str,
    media_id: str,
    source_id: str | None,
    original_url: str | None,
    source_order: int | None,
) -> None:
    if not source_id or not original_url:
        return
    order = int(source_order) if source_order is not None else _next_source_order(house_id, source_id)
    timestamp = now_iso()
    with connect() as con:
        con.execute(
            """
            INSERT INTO media_source_positions (
                house_id, media_id, source_id, original_url, source_order, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(house_id, source_id, original_url) DO UPDATE SET
                media_id = excluded.media_id,
                source_order = excluded.source_order,
                updated_at = excluded.updated_at
            """,
            (house_id, media_id, source_id, original_url, order, timestamp, timestamp),
        )
        con.execute(
            """
            UPDATE media_assets
            SET source_order = ?
            WHERE id = ? AND source_id = ?
            """,
            (order, media_id, source_id),
        )
        con.commit()


def add_media_ordered(house_id: str, data: dict[str, Any]) -> dict[str, Any]:
    if not _ORIGINAL_ADD_MEDIA:
        raise RuntimeError("Ursprüngliche Medienfunktion ist nicht registriert")
    media = _ORIGINAL_ADD_MEDIA(house_id, data)
    if str(data.get("kind") or "image") == "image":
        _record_source_position(
            house_id,
            str(media.get("id") or ""),
            str(data.get("source_id") or "") or None,
            str(data.get("original_url") or "") or None,
            data.get("source_order"),
        )
    return media


def queue_media_ordered(house_id: str, source_id: str, parsed: Any) -> None:
    for index, image_url in enumerate(list(getattr(parsed, "image_urls", None) or [])):
        add_media_ordered(
            house_id,
            {
                "source_id": source_id,
                "kind": "image",
                "original_url": image_url,
                "download_status": "pending",
                "source_order": index,
            },
        )
    for pdf_url in list(getattr(parsed, "pdf_urls", None) or []):
        add_media_ordered(
            house_id,
            {
                "source_id": source_id,
                "kind": "pdf",
                "original_url": pdf_url,
                "download_status": "pending",
            },
        )


def _hex_hash(bits: list[bool]) -> str:
    value = 0
    for bit in bits:
        value = (value << 1) | int(bool(bit))
    width = max(1, (len(bits) + 3) // 4)
    return f"{value:0{width}x}"


def _dhash(image: Image.Image) -> str:
    gray = image.convert("L").resize((9, 8), _RESAMPLE)
    pixels = list(gray.getdata())
    return _hex_hash(
        [pixels[row * 9 + col] > pixels[row * 9 + col + 1] for row in range(8) for col in range(8)]
    )


def _ahash(image: Image.Image) -> str:
    gray = image.convert("L").resize((8, 8), _RESAMPLE)
    pixels = list(gray.getdata())
    average = sum(pixels) / max(1, len(pixels))
    return _hex_hash([value >= average for value in pixels])


def _center_crop(image: Image.Image) -> Image.Image:
    width, height = image.size
    margin_x = max(1, int(width * 0.08))
    margin_y = max(1, int(height * 0.08))
    if width <= margin_x * 2 + 2 or height <= margin_y * 2 + 2:
        return image
    return image.crop((margin_x, margin_y, width - margin_x, height - margin_y))


def _gray_vector(image: Image.Image, size: int = 16) -> list[int]:
    return list(image.convert("L").resize((size, size), _RESAMPLE).getdata())


def _gray_histogram(vector: list[int], bins: int = 16) -> list[float]:
    values = [0] * bins
    for value in vector:
        values[min(bins - 1, int(value) * bins // 256)] += 1
    total = max(1, len(vector))
    return [count / total for count in values]


def _sharpness(image: Image.Image) -> float:
    gray = image.convert("L").resize((32, 32), _RESAMPLE)
    pixels = list(gray.getdata())
    diffs: list[int] = []
    for row in range(32):
        for col in range(31):
            diffs.append(abs(pixels[row * 32 + col] - pixels[row * 32 + col + 1]))
    for row in range(31):
        for col in range(32):
            diffs.append(abs(pixels[row * 32 + col] - pixels[(row + 1) * 32 + col]))
    return sum(diffs) / max(1, len(diffs))


def _fingerprint(path: Path, media: dict[str, Any]) -> dict[str, Any] | None:
    try:
        with Image.open(path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            width, height = image.size
            vector = _gray_vector(image)
            center = _center_crop(image)
            content_hash = str(media.get("content_hash") or "")
            if not content_hash:
                content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            area = max(1, width * height)
            file_size = int(media.get("file_size_bytes") or path.stat().st_size)
            sharpness = _sharpness(image)
            quality = math.log1p(area) * 10.0 + math.log1p(max(1, file_size)) + sharpness * 0.35
            return {
                "content_hash": content_hash,
                "width": width,
                "height": height,
                "dhash": _dhash(image),
                "ahash": _ahash(image),
                "center_hash": _dhash(center),
                "vector": vector,
                "center_vector": _gray_vector(center),
                "histogram": _gray_histogram(vector),
                "quality": quality,
                "file_size": file_size,
            }
    except (UnidentifiedImageError, OSError, ValueError):
        return None


def _load_fingerprint(media: dict[str, Any]) -> dict[str, Any] | None:
    path = Path(str(media.get("local_path") or ""))
    try:
        path.resolve().relative_to(PROJECTS_DIR.resolve())
    except Exception:
        return None
    if not path.exists() or not path.is_file():
        return None

    if int(media.get("dedupe_version") or 0) == DEDUPE_VERSION and media.get("visual_signature"):
        try:
            stored = json.loads(str(media["visual_signature"]))
            if stored.get("vector") and stored.get("dhash"):
                return stored
        except Exception:
            pass

    result = _fingerprint(path, media)
    if not result:
        return None
    with connect() as con:
        con.execute(
            """
            UPDATE media_assets
            SET content_hash = ?, width = ?, height = ?, file_size_bytes = ?,
                perceptual_hash = ?, average_hash = ?, center_hash = ?,
                visual_signature = ?, quality_score = ?, dedupe_version = ?
            WHERE id = ?
            """,
            (
                result["content_hash"],
                result["width"],
                result["height"],
                result["file_size"],
                result["dhash"],
                result["ahash"],
                result["center_hash"],
                json.dumps(result, separators=(",", ":")),
                result["quality"],
                DEDUPE_VERSION,
                media["id"],
            ),
        )
        con.commit()
    return result


def _hash_distance(left: str | None, right: str | None) -> int:
    if not left or not right:
        return 999
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except Exception:
        return 999


def _normalized_mad(left: list[int], right: list[int]) -> float:
    if not left or len(left) != len(right):
        return 999.0
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    return sum(abs((a - left_mean) - (b - right_mean)) for a, b in zip(left, right)) / len(left)


def _histogram_distance(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 999.0
    return sum(abs(a - b) for a, b in zip(left, right)) / 2.0


def _visual_duplicate(left: dict[str, Any], right: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    if left.get("content_hash") and left.get("content_hash") == right.get("content_hash"):
        return True, "exact_hash", {"content_hash": left.get("content_hash")}

    left_ratio = float(left.get("width") or 1) / max(1.0, float(left.get("height") or 1))
    right_ratio = float(right.get("width") or 1) / max(1.0, float(right.get("height") or 1))
    ratio_delta = abs(math.log(max(0.0001, left_ratio / right_ratio)))
    dhash_distance = _hash_distance(left.get("dhash"), right.get("dhash"))
    ahash_distance = _hash_distance(left.get("ahash"), right.get("ahash"))
    center_distance = _hash_distance(left.get("center_hash"), right.get("center_hash"))
    pixel_distance = _normalized_mad(left.get("vector") or [], right.get("vector") or [])
    center_pixel_distance = _normalized_mad(
        left.get("center_vector") or [],
        right.get("center_vector") or [],
    )
    histogram_distance = _histogram_distance(
        left.get("histogram") or [],
        right.get("histogram") or [],
    )

    details = {
        "ratio_delta": round(ratio_delta, 4),
        "dhash_distance": dhash_distance,
        "ahash_distance": ahash_distance,
        "center_distance": center_distance,
        "pixel_distance": round(pixel_distance, 3),
        "center_pixel_distance": round(center_pixel_distance, 3),
        "histogram_distance": round(histogram_distance, 4),
    }

    same_frame = (
        ratio_delta <= 0.08
        and dhash_distance <= 6
        and ahash_distance <= 7
        and pixel_distance <= 13.0
    )
    recompressed = (
        ratio_delta <= 0.07
        and dhash_distance <= 8
        and ahash_distance <= 8
        and pixel_distance <= 10.5
        and histogram_distance <= 0.12
    )
    mildly_cropped = (
        ratio_delta <= 0.17
        and center_distance <= 5
        and center_pixel_distance <= 10.5
        and histogram_distance <= 0.14
        and min(dhash_distance, ahash_distance) <= 10
    )
    if same_frame:
        return True, "visual_same_frame", details
    if recompressed:
        return True, "visual_recompressed", details
    if mildly_cropped:
        return True, "visual_mild_crop", details
    return False, "", details


def _source_positions(house_id: str) -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute(
            """
            SELECT p.*, s.source_name, s.created_at AS source_created_at
            FROM media_source_positions p
            LEFT JOIN listing_sources s ON s.id = p.source_id
            WHERE p.house_id = ?
            ORDER BY COALESCE(s.created_at, p.created_at), p.source_order
            """,
            (house_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _remove_known_empty_duplicates(house_id: str) -> int:
    removed = 0
    with connect() as con:
        rows = con.execute(
            """
            SELECT * FROM media_assets
            WHERE house_id = ? AND kind = 'image' AND download_status = 'skipped'
              AND (local_path IS NULL OR local_path = '')
              AND download_error LIKE '%Duplikat von Medium %'
            """,
            (house_id,),
        ).fetchall()
        for row in rows:
            match = re.search(r"Duplikat von Medium\s+([A-Za-z0-9_-]+)", str(row["download_error"] or ""))
            keeper_id = match.group(1) if match else None
            if keeper_id:
                keeper = con.execute(
                    "SELECT id FROM media_assets WHERE id = ? AND house_id = ?",
                    (keeper_id, house_id),
                ).fetchone()
                if keeper:
                    con.execute(
                        "UPDATE media_source_positions SET media_id = ?, updated_at = ? WHERE media_id = ?",
                        (keeper_id, now_iso(), row["id"]),
                    )
            con.execute("DELETE FROM media_assets WHERE id = ?", (row["id"],))
            removed += 1
        con.commit()
    return removed


def cleanup_house_media(house_id: str) -> dict[str, Any]:
    ensure_media_quality_schema()
    empty_removed = _remove_known_empty_duplicates(house_id)

    with connect() as con:
        rows = con.execute(
            """
            SELECT m.*, s.source_name, s.created_at AS source_created_at
            FROM media_assets m
            LEFT JOIN listing_sources s ON s.id = m.source_id
            WHERE m.house_id = ? AND m.kind = 'image'
              AND m.local_path IS NOT NULL AND m.local_path <> ''
              AND m.download_status IN ('downloaded', 'skipped')
            ORDER BY m.created_at, m.id
            """,
            (house_id,),
        ).fetchall()
    media_items = [dict(row) for row in rows]
    fingerprints: dict[str, dict[str, Any]] = {}
    usable: list[dict[str, Any]] = []
    for item in media_items:
        fingerprint = _load_fingerprint(item)
        if fingerprint:
            fingerprints[str(item["id"])] = fingerprint
            usable.append(item)

    parent = {str(item["id"]): str(item["id"]) for item in usable}
    duplicate_details: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}

    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for index, left_item in enumerate(usable):
        left_id = str(left_item["id"])
        for right_item in usable[index + 1 :]:
            right_id = str(right_item["id"])
            duplicate, method, details = _visual_duplicate(fingerprints[left_id], fingerprints[right_id])
            if duplicate:
                union(left_id, right_id)
                duplicate_details[(left_id, right_id)] = (method, details)

    clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in usable:
        clusters[find(str(item["id"]))].append(item)

    positions = _source_positions(house_id)
    item_to_root = {str(item["id"]): find(str(item["id"])) for item in usable}
    source_roots: dict[str, set[str]] = defaultdict(set)
    source_created: dict[str, str] = {}
    root_positions: dict[str, dict[str, int]] = defaultdict(dict)
    for position in positions:
        media_id = str(position.get("media_id") or "")
        root = item_to_root.get(media_id)
        source_id = str(position.get("source_id") or "")
        if not root or not source_id:
            continue
        source_roots[source_id].add(root)
        source_created[source_id] = str(position.get("source_created_at") or position.get("created_at") or "")
        order = int(position.get("source_order") or 0)
        current = root_positions[root].get(source_id)
        root_positions[root][source_id] = order if current is None else min(current, order)

    primary_source = None
    if source_roots:
        primary_source = sorted(
            source_roots,
            key=lambda source_id: (-len(source_roots[source_id]), source_created.get(source_id, ""), source_id),
        )[0]

    keepers: dict[str, dict[str, Any]] = {}
    for root, members in clusters.items():
        ranked = sorted(
            members,
            key=lambda item: (
                float(fingerprints[str(item["id"])].get("quality") or 0.0),
                int(fingerprints[str(item["id"])].get("width") or 0)
                * int(fingerprints[str(item["id"])].get("height") or 0),
                int(fingerprints[str(item["id"])].get("file_size") or 0),
            ),
            reverse=True,
        )
        best = ranked[0]
        if primary_source:
            primary_members = [
                item
                for item in ranked
                if str(item.get("source_id") or "") == primary_source
            ]
            if primary_members:
                primary_best = primary_members[0]
                best_quality = float(fingerprints[str(best["id"])].get("quality") or 0.0)
                primary_quality = float(fingerprints[str(primary_best["id"])].get("quality") or 0.0)
                if primary_quality >= best_quality * 0.90:
                    best = primary_best
        keepers[root] = best

    removed = empty_removed
    removed_files = 0
    with connect() as con:
        house_columns = {row[1] for row in con.execute("PRAGMA table_info(houses)").fetchall()}
        media_columns = {row[1] for row in con.execute("PRAGMA table_info(media_assets)").fetchall()}
        for root, members in clusters.items():
            keeper = keepers[root]
            keeper_id = str(keeper["id"])
            con.execute(
                "UPDATE media_assets SET download_status = 'downloaded', download_error = NULL WHERE id = ?",
                (keeper_id,),
            )
            for member in members:
                member_id = str(member["id"])
                if member_id == keeper_id:
                    continue
                method = "visual_cluster"
                details: dict[str, Any] = {}
                direct = duplicate_details.get((member_id, keeper_id)) or duplicate_details.get((keeper_id, member_id))
                if direct:
                    method, details = direct
                con.execute(
                    "UPDATE media_source_positions SET media_id = ?, updated_at = ? WHERE media_id = ?",
                    (keeper_id, now_iso(), member_id),
                )
                if "preview_media_id" in house_columns:
                    con.execute(
                        "UPDATE houses SET preview_media_id = ? WHERE id = ? AND preview_media_id = ?",
                        (keeper_id, house_id, member_id),
                    )
                if "parent_media_id" in media_columns:
                    con.execute(
                        "UPDATE media_assets SET parent_media_id = ? WHERE parent_media_id = ?",
                        (keeper_id, member_id),
                    )
                removed_path = str(member.get("local_path") or "")
                con.execute(
                    """
                    INSERT INTO media_cleanup_events (
                        id, house_id, removed_media_id, kept_media_id, method,
                        details_json, removed_path, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uuid.uuid4().hex[:12],
                        house_id,
                        member_id,
                        keeper_id,
                        method,
                        json.dumps(details, ensure_ascii=False),
                        removed_path or None,
                        now_iso(),
                    ),
                )
                con.execute("DELETE FROM media_assets WHERE id = ?", (member_id,))
                keeper_path = str(keeper.get("local_path") or "")
                if removed_path and removed_path != keeper_path:
                    path = Path(removed_path)
                    try:
                        path.resolve().relative_to(PROJECTS_DIR.resolve())
                        if path.exists() and path.is_file():
                            path.unlink()
                            removed_files += 1
                    except Exception:
                        pass
                removed += 1
        con.commit()

    remaining_ids = {str(item["id"]) for item in keepers.values()}
    positions = _source_positions(house_id)
    source_to_media: dict[str, dict[str, int]] = defaultdict(dict)
    source_created = {}
    for position in positions:
        media_id = str(position.get("media_id") or "")
        source_id = str(position.get("source_id") or "")
        if media_id not in remaining_ids or not source_id:
            continue
        order = int(position.get("source_order") or 0)
        current = source_to_media[source_id].get(media_id)
        source_to_media[source_id][media_id] = order if current is None else min(current, order)
        source_created[source_id] = str(position.get("source_created_at") or position.get("created_at") or "")

    ordered_ids: list[str] = []
    if primary_source and primary_source in source_to_media:
        ordered_ids.extend(
            media_id
            for media_id, _ in sorted(source_to_media[primary_source].items(), key=lambda pair: (pair[1], pair[0]))
        )
    for source_id in sorted(
        source_to_media,
        key=lambda value: (0 if value == primary_source else 1, source_created.get(value, ""), value),
    ):
        if source_id == primary_source:
            continue
        for media_id, _ in sorted(source_to_media[source_id].items(), key=lambda pair: (pair[1], pair[0])):
            if media_id not in ordered_ids:
                ordered_ids.append(media_id)

    remaining_by_created = sorted(
        keepers.values(),
        key=lambda item: (
            int(item.get("source_order") or 999999),
            str(item.get("created_at") or ""),
            str(item.get("id") or ""),
        ),
    )
    for item in remaining_by_created:
        media_id = str(item["id"])
        if media_id not in ordered_ids:
            ordered_ids.append(media_id)

    with connect() as con:
        for display_order, media_id in enumerate(ordered_ids):
            con.execute(
                "UPDATE media_assets SET display_order = ?, download_status = 'downloaded', download_error = NULL WHERE id = ?",
                (display_order, media_id),
            )
        con.commit()

    return {
        "house_id": house_id,
        "before": len(media_items) + empty_removed,
        "after": len(ordered_ids),
        "removed": removed,
        "removed_files": removed_files,
        "primary_source_id": primary_source,
    }


def cleanup_all_houses() -> dict[str, Any]:
    summary = {"houses": 0, "removed": 0, "errors": []}
    for house in list_houses():
        house_id = str(house.get("id") or "")
        if not house_id:
            continue
        try:
            result = cleanup_house_media(house_id)
            summary["houses"] += 1
            summary["removed"] += int(result.get("removed") or 0)
        except Exception as exc:
            summary["errors"].append({"house_id": house_id, "error": str(exc)[:300]})
    return summary


def ordered_image_items(house_id: str) -> list[dict[str, Any]]:
    ensure_media_quality_schema()
    with connect() as con:
        rows = con.execute(
            """
            SELECT m.*, s.source_name, s.created_at AS source_created_at
            FROM media_assets m
            LEFT JOIN listing_sources s ON s.id = m.source_id
            WHERE m.house_id = ? AND m.kind = 'image'
              AND m.download_status = 'downloaded'
              AND m.local_path IS NOT NULL AND m.local_path <> ''
            ORDER BY COALESCE(m.display_order, 999999),
                     COALESCE(m.source_order, 999999),
                     COALESCE(s.created_at, m.created_at),
                     m.created_at,
                     m.id
            """,
            (house_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def first_local_image_v2(house_id: str) -> str | None:
    images = ordered_image_items(house_id)
    return f"media/{images[0]['id']}" if images else None


def hero_image_v2(house: dict[str, Any]) -> str:
    import app.modern_ui as modern_ui

    house_id = str(house.get("id") or "")
    selected = str(house.get("preview_media_id") or "")
    images = ordered_image_items(house_id)
    if selected and any(str(item.get("id") or "") == selected for item in images):
        return f"../media/{modern_ui.esc(selected)}"
    if images:
        return f"../media/{modern_ui.esc(images[0].get('id'))}"
    preview = str(house.get("preview_image_url") or "").strip()
    return modern_ui.esc(preview) if preview else ""


def _resized_jpeg_bytes_v2(path: Path, max_size: int = AI_IMAGE_MAX_SIZE) -> bytes:
    try:
        with Image.open(path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.thumbnail((max_size, max_size), _RESAMPLE)
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=AI_IMAGE_QUALITY, optimize=True)
            return output.getvalue()
    except UnidentifiedImageError:
        return path.read_bytes()


def _even_indices(total: int, count: int) -> list[int]:
    if count >= total:
        return list(range(total))
    if count <= 1:
        return [0]
    values = {round(index * (total - 1) / (count - 1)) for index in range(count)}
    values.add(0)
    values.add(total - 1)
    return sorted(values)


def ai_image_paths(house_id: str) -> list[tuple[dict[str, Any], Path]]:
    cleanup_house_media(house_id)
    candidates: list[tuple[dict[str, Any], Path, int]] = []
    for item in ordered_image_items(house_id):
        path = Path(str(item.get("local_path") or ""))
        try:
            path.resolve().relative_to(PROJECTS_DIR.resolve())
        except Exception:
            continue
        if not path.exists() or not path.is_file():
            continue
        try:
            resized_size = len(_resized_jpeg_bytes_v2(path))
        except Exception:
            resized_size = int(item.get("file_size_bytes") or path.stat().st_size)
        candidates.append((item, path, resized_size))

    total_count = len(candidates)
    total_bytes = sum(item[2] for item in candidates)
    mode = "all"
    selected = candidates
    if total_count > AI_IMAGE_MAX_COUNT or total_bytes > AI_IMAGE_BUDGET_BYTES:
        mode = "balanced_across_full_gallery"
        max_count = min(AI_IMAGE_MAX_COUNT, total_count)
        selected = []
        for count in range(max_count, max(11, min(18, max_count)) - 1, -1):
            indices = _even_indices(total_count, count)
            attempt = [candidates[index] for index in indices]
            if sum(item[2] for item in attempt) <= AI_IMAGE_BUDGET_BYTES:
                selected = attempt
                break
        if not selected:
            selected = []
            used = 0
            for index in _even_indices(total_count, min(total_count, 18)):
                candidate = candidates[index]
                if selected and used + candidate[2] > AI_IMAGE_BUDGET_BYTES:
                    continue
                selected.append(candidate)
                used += candidate[2]

    _LAST_SELECTION[house_id] = {
        "selection_mode": mode,
        "total_unique_images": total_count,
        "exported_images": len(selected),
        "omitted_images": max(0, total_count - len(selected)),
        "resized_bytes_estimated": sum(item[2] for item in selected),
        "images": [
            {
                "media_id": item.get("id"),
                "display_order": item.get("display_order"),
                "source_order": item.get("source_order"),
                "source_name": item.get("source_name"),
                "original_url": item.get("original_url"),
                "width": item.get("width"),
                "height": item.get("height"),
            }
            for item, _path, _size in selected
        ],
    }
    return [(item, path) for item, path, _size in selected]


def readme_prompt_v2(house_id: str) -> str:
    base = _ORIGINAL_README(house_id) if _ORIGINAL_README else ""
    return base + """

## Vollständige Bildprüfung

`image_selection.json` beschreibt die Bildauswahl und die ursprüngliche Galeriereihenfolge.
Prüfe **jedes** exportierte Bild, nicht nur die ersten Dateien. Die Reihenfolge folgt der
vollständigsten Inseratgalerie; zusätzliche, nur bei anderen Anbietern vorhandene Bilder werden
danach in deren jeweiliger Portalreihenfolge ergänzt.

Gehe die Bilder mindestens in diesen Gruppen durch:

- Außenansichten, Grundstück, Zufahrt, Fassade und Dach
- Wohnräume, Küche, Bäder und Schlafräume
- Keller, Technik, Nebenräume, Nebengebäude und Garage
- Grundrisse, Pläne und sonstige Unterlagen

Ziehe die Schlussfolgerung „kaum Innenansichten vorhanden“ erst, nachdem alle exportierten Bilder
geprüft wurden. Späte Bildnummern sind ausdrücklich genauso wichtig wie die ersten. Dokumentiere
im Ergebnis unter `image_coverage`, wie viele Innen-, Außen-, Technik-/Nebenraum- und Planbilder
tatsächlich geprüft wurden.
"""


def analysis_schema_v2(house_id: str) -> dict[str, Any]:
    schema = _ORIGINAL_SCHEMA(house_id) if _ORIGINAL_SCHEMA else {"type": "object", "properties": {}}
    properties = schema.setdefault("properties", {})
    properties["image_coverage"] = {
        "type": "object",
        "properties": {
            "exported_images_reviewed": {"type": "integer", "minimum": 0},
            "exterior_images": {"type": "integer", "minimum": 0},
            "interior_images": {"type": "integer", "minimum": 0},
            "technical_or_outbuilding_images": {"type": "integer", "minimum": 0},
            "plans_or_documents": {"type": "integer", "minimum": 0},
            "unclassified_images": {"type": "integer", "minimum": 0},
            "comment": {"type": "string"},
        },
    }
    return schema


def create_analysis_zip_v2(house_id: str) -> Path:
    if not _ORIGINAL_CREATE_ZIP:
        raise RuntimeError("Analyseexport ist nicht registriert")
    cleanup = cleanup_house_media(house_id)
    target = _ORIGINAL_CREATE_ZIP(house_id)
    selection = _LAST_SELECTION.get(
        house_id,
        {
            "selection_mode": "none",
            "total_unique_images": 0,
            "exported_images": 0,
            "omitted_images": 0,
            "images": [],
        },
    )
    selection["media_cleanup"] = cleanup
    with zipfile.ZipFile(target, "a", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "image_selection.json",
            json.dumps(selection, ensure_ascii=False, indent=2),
        )
    return target


async def download_with_cleanup(house_id: str, limit: int = 120) -> None:
    if not _ORIGINAL_DOWNLOAD:
        return
    await _ORIGINAL_DOWNLOAD(house_id, limit)
    cleanup_house_media(house_id)


def _patch_exporters() -> None:
    import app.analysis_package as analysis_package
    import app.github_auto_export as github_auto_export
    import app.github_exchange as github_exchange
    import app.gmail_exchange as gmail_exchange

    analysis_package.EXPORT_IMAGE_LIMIT = AI_IMAGE_MAX_COUNT
    analysis_package.local_image_paths = ai_image_paths
    analysis_package.resized_jpeg_bytes = _resized_jpeg_bytes_v2
    analysis_package.readme_prompt = readme_prompt_v2
    analysis_package.analysis_schema = analysis_schema_v2
    analysis_package.create_analysis_zip = create_analysis_zip_v2
    github_auto_export.create_analysis_zip = create_analysis_zip_v2
    github_exchange.create_analysis_zip = create_analysis_zip_v2
    gmail_exchange.create_analysis_zip = create_analysis_zip_v2


def register_media_quality_v2(app: FastAPI) -> None:
    global _PATCHED
    global _ORIGINAL_ADD_MEDIA, _ORIGINAL_QUEUE_MEDIA, _ORIGINAL_DOWNLOAD
    global _ORIGINAL_CREATE_ZIP, _ORIGINAL_README, _ORIGINAL_SCHEMA
    if _PATCHED:
        return

    import app.analysis_package as analysis_package
    import app.house_manage as house_manage
    import app.immoscout_support as support
    import app.import_patch as import_patch
    import app.main as main
    import app.modern_ui as modern_ui
    import app.storage as storage

    ensure_media_quality_schema()

    _ORIGINAL_ADD_MEDIA = storage.add_media
    _ORIGINAL_QUEUE_MEDIA = support._queue_media
    _ORIGINAL_DOWNLOAD = main.download_pending_media_files
    _ORIGINAL_CREATE_ZIP = analysis_package.create_analysis_zip
    _ORIGINAL_README = analysis_package.readme_prompt
    _ORIGINAL_SCHEMA = analysis_package.analysis_schema

    storage.add_media = add_media_ordered
    main.add_media = add_media_ordered
    import_patch.add_media = add_media_ordered
    support.add_media = add_media_ordered
    house_manage.add_media = add_media_ordered
    modern_ui.add_media = add_media_ordered
    support._queue_media = queue_media_ordered

    support.dedupe_house_images_perceptually = cleanup_house_media
    main.download_pending_media_files = download_with_cleanup
    import_patch.download_pending_media_files = download_with_cleanup

    house_manage.image_items = ordered_image_items
    modern_ui._house_images = ordered_image_items
    modern_ui._hero_image = hero_image_v2
    main.first_local_image = first_local_image_v2

    _patch_exporters()

    @app.post("/houses/{house_id}/media/cleanup")
    async def cleanup_house_media_route(house_id: str) -> RedirectResponse:
        cleanup_house_media(house_id)
        return RedirectResponse(f"../../../houses/{house_id}", status_code=303)

    summary = cleanup_all_houses()
    print(
        f"HausCheck Medienbereinigung: {summary['houses']} Hausakten geprüft, "
        f"{summary['removed']} überflüssige Bilder entfernt.",
        flush=True,
    )
    _PATCHED = True
