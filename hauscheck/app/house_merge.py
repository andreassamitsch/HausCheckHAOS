from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import RedirectResponse

import app.analysis_package as analysis_package
import app.focused_ui as focused_ui
import app.house_manage as house_manage
import app.product_ui as product_ui
from app.github_auto_export import auto_export_house_to_github
from app.pipeline_status import set_pipeline_stage
from app.storage import (
    PROJECTS_DIR,
    connect,
    ensure_columns,
    get_house,
    get_media,
    list_houses,
    list_media,
    list_sources,
    now_iso,
    project_dir,
    row_to_dict,
)
from app.ui_helpers import esc, format_datetime


_patched = False

MERGE_FILL_FIELDS = [
    "location_text",
    "address_status",
    "exact_address",
    "price_eur",
    "living_area_m2",
    "plot_area_m2",
    "rooms",
    "year_built",
    "heating",
    "energy_hwb",
    "energy_fgee",
    "energy_class_hwb",
    "energy_class_fgee",
]

MERGE_CSS = """
<style>
  .merge-card select { width:100%; }
  .merge-warning { padding:10px 12px; border-radius:10px; background:#3b2c18; border:1px solid #6e532c; color:#ffe7b5; }
  .preview-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:10px; }
  .preview-tile { position:relative; overflow:hidden; border-radius:12px; background:#101820; border:1px solid #293744; }
  .preview-tile.selected { border:2px solid #38a169; }
  .preview-tile img { width:100%; height:125px; object-fit:cover; display:block; }
  .preview-tile-actions { padding:7px; display:flex; align-items:center; justify-content:center; min-height:42px; }
  .preview-tile-actions form { margin:0; width:100%; }
  .preview-tile-actions button { margin:0; width:100%; padding:7px 8px; font-size:13px; }
  .preview-badge { display:inline-block; padding:5px 8px; border-radius:999px; background:#245c3a; color:#e6fff0; font-size:12px; font-weight:700; }
  .hero-gallery-card .preview-current { margin:8px 10px 0; }
</style>
"""


def ensure_house_merge_schema() -> None:
    with connect() as con:
        ensure_columns(
            con,
            "houses",
            {
                "preview_media_id": "TEXT",
            },
        )
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS house_merge_events (
                id TEXT PRIMARY KEY,
                target_house_id TEXT NOT NULL,
                source_house_id TEXT NOT NULL,
                target_title TEXT,
                source_title TEXT,
                target_snapshot_json TEXT,
                source_snapshot_json TEXT,
                moved_sources INTEGER NOT NULL DEFAULT 0,
                moved_media INTEGER NOT NULL DEFAULT 0,
                removed_duplicate_media INTEGER NOT NULL DEFAULT 0,
                moved_evidence INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_house_merge_events_target
                ON house_merge_events(target_house_id, created_at DESC);
            """
        )
        con.commit()


def _safe_filename(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", value or "file")
    return name[:160] or "file"


def _copy_to_target(source_path: object, target_house_id: str, subdir: str, prefix: str) -> str | None:
    raw = str(source_path or "").strip()
    if not raw:
        return None
    source = Path(raw)
    try:
        source.resolve().relative_to(PROJECTS_DIR.resolve())
    except Exception:
        return raw
    if not source.exists() or not source.is_file():
        return raw

    target_dir = project_dir(target_house_id) / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = _safe_filename(f"{prefix}_{source.name}")
    target = target_dir / filename
    counter = 2
    while target.exists() and target.resolve() != source.resolve():
        target = target_dir / _safe_filename(f"{prefix}_{counter}_{source.name}")
        counter += 1
    if target.resolve() != source.resolve():
        shutil.copy2(source, target)
    return str(target)


def _media_subdir(kind: object, local_path: object) -> str:
    normalized = str(kind or "").lower()
    if normalized == "image":
        return "images"
    if normalized == "pdf":
        return "pdfs"
    if normalized == "video":
        return "videos"
    if normalized == "screenshot":
        return "screenshots"
    suffix = Path(str(local_path or "")).suffix.lower()
    if suffix == ".pdf":
        return "pdfs"
    return "images"


def _copy_secondary_analysis(source_house_id: str, target_house_id: str) -> None:
    source_dir = PROJECTS_DIR / source_house_id / "analysis"
    if not source_dir.exists():
        return
    target_dir = project_dir(target_house_id) / "analysis"
    for source in source_dir.iterdir():
        if not source.is_file():
            continue
        target = target_dir / _safe_filename(f"merged_from_{source_house_id}_{source.name}")
        counter = 2
        while target.exists():
            target = target_dir / _safe_filename(f"merged_from_{source_house_id}_{counter}_{source.name}")
            counter += 1
        shutil.copy2(source, target)


def _source_duplicate(con: Any, target_house_id: str, source: dict[str, Any]) -> dict[str, Any] | None:
    url = str(source.get("source_url") or "").strip()
    external_id = str(source.get("external_id") or "").strip()
    row = con.execute(
        """
        SELECT * FROM listing_sources
        WHERE house_id = ?
          AND (
              (? <> '' AND source_url = ?)
              OR (? <> '' AND external_id = ?)
          )
        ORDER BY created_at ASC LIMIT 1
        """,
        (target_house_id, url, url, external_id, external_id),
    ).fetchone()
    return row_to_dict(row)


def _media_duplicate(con: Any, target_house_id: str, media: dict[str, Any]) -> dict[str, Any] | None:
    content_hash = str(media.get("content_hash") or "").strip()
    original_url = str(media.get("original_url") or "").strip()
    row = con.execute(
        """
        SELECT * FROM media_assets
        WHERE house_id = ? AND kind = ?
          AND (
              (? <> '' AND content_hash = ?)
              OR (? <> '' AND original_url = ?)
          )
        ORDER BY CASE WHEN download_status = 'downloaded' THEN 0 ELSE 1 END, created_at ASC
        LIMIT 1
        """,
        (
            target_house_id,
            media.get("kind") or "image",
            content_hash,
            content_hash,
            original_url,
            original_url,
        ),
    ).fetchone()
    return row_to_dict(row)


def _combine_notes(target: dict[str, Any], source: dict[str, Any]) -> str | None:
    target_notes = str(target.get("notes") or "").strip()
    source_notes = str(source.get("notes") or "").strip()
    if not source_notes:
        return target_notes or None
    if not target_notes:
        return source_notes
    if source_notes in target_notes:
        return target_notes
    return f"{target_notes}\n\nAus zusammengeführter Hausakte „{source.get('title') or source.get('id')}“:\n{source_notes}"


def merge_houses(target_house_id: str, source_house_id: str) -> dict[str, Any]:
    ensure_house_merge_schema()
    if target_house_id == source_house_id:
        raise ValueError("Eine Hausakte kann nicht mit sich selbst zusammengeführt werden")

    target = get_house(target_house_id)
    source = get_house(source_house_id)
    if not target or not source:
        raise ValueError("Eine der Hausakten wurde nicht gefunden")
    if str(target.get("status") or "") == "rejected" or str(source.get("status") or "") == "rejected":
        raise ValueError("Abgelehnte Hausakten zuerst wiederherstellen")

    _copy_secondary_analysis(source_house_id, target_house_id)
    timestamp = now_iso()
    source_preview_media_id = str(source.get("preview_media_id") or "")
    target_preview_media_id = str(target.get("preview_media_id") or "")
    selected_preview_media_id = target_preview_media_id or None
    moved_sources = 0
    moved_media = 0
    duplicate_media = 0
    moved_evidence = 0

    with connect() as con:
        source_rows = [row_to_dict(row) or {} for row in con.execute(
            "SELECT * FROM listing_sources WHERE house_id = ? ORDER BY created_at ASC",
            (source_house_id,),
        ).fetchall()]
        source_map: dict[str, str] = {}

        for source_row in source_rows:
            old_source_id = str(source_row.get("id") or "")
            duplicate = _source_duplicate(con, target_house_id, source_row)
            if duplicate:
                new_source_id = str(duplicate.get("id") or "")
                source_map[old_source_id] = new_source_id
                con.execute("UPDATE media_assets SET source_id = ? WHERE source_id = ?", (new_source_id, old_source_id))
                con.execute("UPDATE field_evidence SET source_id = ? WHERE source_id = ?", (new_source_id, old_source_id))
                con.execute("DELETE FROM listing_sources WHERE id = ?", (old_source_id,))
                continue

            new_html_path = _copy_to_target(
                source_row.get("raw_html_path"),
                target_house_id,
                "html",
                f"merged_{source_house_id}_{old_source_id}",
            )
            con.execute(
                "UPDATE listing_sources SET house_id = ?, raw_html_path = ?, updated_at = ? WHERE id = ?",
                (target_house_id, new_html_path, timestamp, old_source_id),
            )
            source_map[old_source_id] = old_source_id
            moved_sources += 1

        evidence_count = con.execute(
            "SELECT COUNT(*) FROM field_evidence WHERE house_id = ?",
            (source_house_id,),
        ).fetchone()[0]
        for old_source_id, new_source_id in source_map.items():
            con.execute(
                "UPDATE field_evidence SET source_id = ? WHERE house_id = ? AND source_id = ?",
                (new_source_id, source_house_id, old_source_id),
            )
        con.execute("UPDATE field_evidence SET house_id = ? WHERE house_id = ?", (target_house_id, source_house_id))
        moved_evidence = int(evidence_count or 0)

        media_rows = [row_to_dict(row) or {} for row in con.execute(
            "SELECT * FROM media_assets WHERE house_id = ? ORDER BY created_at ASC",
            (source_house_id,),
        ).fetchall()]
        for media in media_rows:
            media_id = str(media.get("id") or "")
            duplicate = _media_duplicate(con, target_house_id, media)
            if duplicate:
                duplicate_id = str(duplicate.get("id") or "")
                # Ein bereits vorhandener, aber noch nicht geladener Datensatz übernimmt die bessere lokale Datei.
                if (
                    str(duplicate.get("download_status") or "") != "downloaded"
                    and str(media.get("download_status") or "") == "downloaded"
                    and media.get("local_path")
                ):
                    new_path = _copy_to_target(
                        media.get("local_path"),
                        target_house_id,
                        _media_subdir(media.get("kind"), media.get("local_path")),
                        f"merged_{source_house_id}_{media_id}",
                    )
                    con.execute(
                        """
                        UPDATE media_assets
                        SET local_path = ?, mime_type = ?, download_status = 'downloaded', download_error = NULL,
                            content_hash = COALESCE(?, content_hash), width = COALESCE(?, width),
                            height = COALESCE(?, height), file_size_bytes = COALESCE(?, file_size_bytes)
                        WHERE id = ?
                        """,
                        (
                            new_path,
                            media.get("mime_type"),
                            media.get("content_hash"),
                            media.get("width"),
                            media.get("height"),
                            media.get("file_size_bytes"),
                            duplicate_id,
                        ),
                    )
                if source_preview_media_id == media_id and not selected_preview_media_id:
                    selected_preview_media_id = duplicate_id
                con.execute("DELETE FROM media_assets WHERE id = ?", (media_id,))
                duplicate_media += 1
                continue

            new_path = _copy_to_target(
                media.get("local_path"),
                target_house_id,
                _media_subdir(media.get("kind"), media.get("local_path")),
                f"merged_{source_house_id}_{media_id}",
            )
            mapped_source_id = source_map.get(str(media.get("source_id") or ""), media.get("source_id"))
            con.execute(
                "UPDATE media_assets SET house_id = ?, source_id = ?, local_path = ? WHERE id = ?",
                (target_house_id, mapped_source_id, new_path, media_id),
            )
            if source_preview_media_id == media_id and not selected_preview_media_id:
                selected_preview_media_id = media_id
            moved_media += 1

        con.execute(
            "UPDATE search_candidates SET imported_house_id = ?, status = 'imported' WHERE imported_house_id = ?",
            (target_house_id, source_house_id),
        )
        con.execute(
            "UPDATE house_pipeline_events SET house_id = ?, message = '[Zusammengeführt] ' || COALESCE(message, '') WHERE house_id = ?",
            (target_house_id, source_house_id),
        )
        con.execute("DELETE FROM house_pipeline_status WHERE house_id = ?", (source_house_id,))

        updates: dict[str, Any] = {}
        for field in MERGE_FILL_FIELDS:
            target_value = target.get(field)
            source_value = source.get(field)
            if target_value in (None, "", "unknown") and source_value not in (None, "", "unknown"):
                updates[field] = source_value
        notes = _combine_notes(target, source)
        if notes != target.get("notes"):
            updates["notes"] = notes
        if not target.get("preview_image_url") and source.get("preview_image_url"):
            updates["preview_image_url"] = source.get("preview_image_url")
        if selected_preview_media_id:
            updates["preview_media_id"] = selected_preview_media_id
        updates["updated_at"] = timestamp
        if updates:
            sql = ", ".join(f"{key} = ?" for key in updates)
            con.execute(f"UPDATE houses SET {sql} WHERE id = ?", list(updates.values()) + [target_house_id])

        con.execute(
            """
            INSERT INTO house_merge_events (
                id, target_house_id, source_house_id, target_title, source_title,
                target_snapshot_json, source_snapshot_json, moved_sources, moved_media,
                removed_duplicate_media, moved_evidence, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex[:12],
                target_house_id,
                source_house_id,
                target.get("title"),
                source.get("title"),
                json.dumps(target, ensure_ascii=False, default=str),
                json.dumps(source, ensure_ascii=False, default=str),
                moved_sources,
                moved_media,
                duplicate_media,
                moved_evidence,
                timestamp,
            ),
        )
        con.execute("DELETE FROM houses WHERE id = ?", (source_house_id,))
        con.commit()

    source_dir = PROJECTS_DIR / source_house_id
    try:
        source_dir.resolve().relative_to(PROJECTS_DIR.resolve())
        if source_dir.exists():
            shutil.rmtree(source_dir)
    except Exception:
        pass

    set_pipeline_stage(
        target_house_id,
        "media_ready",
        "ok",
        f"Hausakte „{source.get('title') or source_house_id}“ wurde zusammengeführt: {moved_sources} Quelle(n), {moved_media} Medien, {duplicate_media} Duplikat(e) entfernt.",
    )
    return {
        "target_house_id": target_house_id,
        "source_house_id": source_house_id,
        "moved_sources": moved_sources,
        "moved_media": moved_media,
        "removed_duplicate_media": duplicate_media,
        "moved_evidence": moved_evidence,
    }


def set_preview_media(house_id: str, media_id: str | None) -> None:
    ensure_house_merge_schema()
    if not get_house(house_id):
        raise ValueError("Hausakte nicht gefunden")
    if media_id:
        media = get_media(media_id)
        if not media or str(media.get("house_id") or "") != house_id:
            raise ValueError("Bild gehört nicht zu dieser Hausakte")
        if media.get("kind") != "image" or media.get("download_status") != "downloaded":
            raise ValueError("Nur ein geladenes Galeriebild kann als Vorschaubild verwendet werden")
    with connect() as con:
        con.execute(
            "UPDATE houses SET preview_media_id = ?, updated_at = ? WHERE id = ?",
            (media_id, now_iso(), house_id),
        )
        con.commit()


def _selected_image_items(house_id: str) -> list[dict[str, Any]]:
    house = get_house(house_id) or {}
    selected = str(house.get("preview_media_id") or "")
    items = [
        item
        for item in list_media(house_id)
        if item.get("kind") == "image"
        and item.get("download_status") == "downloaded"
        and item.get("local_path")
    ]
    items.sort(
        key=lambda item: (
            0 if str(item.get("id") or "") == selected else 1,
            str(item.get("created_at") or ""),
        )
    )
    return items


def preview_for_dashboard(house: dict[str, Any]) -> str:
    house_id = str(house.get("id") or "")
    selected = str(house.get("preview_media_id") or "")
    if selected:
        media = get_media(selected)
        if (
            media
            and str(media.get("house_id") or "") == house_id
            and media.get("kind") == "image"
            and media.get("download_status") == "downloaded"
        ):
            return f'<img src="media/{esc(selected)}" alt="Ausgewähltes Vorschaubild">'
    preview_url = str(house.get("preview_image_url") or "").strip()
    if preview_url:
        return f'<img src="{esc(preview_url)}" alt="Vorschaubild">'
    items = _selected_image_items(house_id)
    if items:
        return f'<img src="media/{esc(items[0].get("id"))}" alt="Hausbild">'
    return '<div class="listing-no-image">Noch kein Bild</div>'


def hero_gallery_html(house_id: str) -> str:
    items = _selected_image_items(house_id)
    if not items:
        return ""
    house = get_house(house_id) or {}
    selected = str(house.get("preview_media_id") or "")
    slides = []
    for item in items[:16]:
        media_id = esc(item.get("id"))
        slides.append(
            f"""
            <a class="hero-slide" href="../media/{media_id}" target="_blank" title="Bild groß öffnen">
              <img src="../media/{media_id}" alt="Bild">
            </a>
            """
        )
    selected_text = "Ausgewähltes Vorschaubild wird zuerst angezeigt." if selected else "Unter Bilder kann ein Galeriebild als Vorschaubild gewählt werden."
    return f"""
    <div class="hero-gallery-card">
      <div class="hero-gallery">{''.join(slides)}</div>
      <div class="muted hero-hint">Seitlich wischen · Bild antippen zum groß Öffnen</div>
      <div class="muted preview-current">{esc(selected_text)}</div>
    </div>
    """


def preview_image_grid_html(house_id: str) -> str:
    items = _selected_image_items(house_id)
    if not items:
        return "<p class='muted'>Noch keine heruntergeladenen Bilder.</p>"
    house = get_house(house_id) or {}
    selected = str(house.get("preview_media_id") or "")
    tiles: list[str] = []
    for item in items:
        media_id = str(item.get("id") or "")
        is_selected = media_id == selected
        action = (
            '<span class="preview-badge">✓ Vorschaubild</span>'
            if is_selected
            else f"""
            <form method="post" action="{esc(house_id)}/preview/{esc(media_id)}" data-no-loading="true">
              <button class="secondary" type="submit">Als Vorschaubild</button>
            </form>
            """
        )
        tiles.append(
            f"""
            <div class="preview-tile {'selected' if is_selected else ''}">
              <a href="../media/{esc(media_id)}" target="_blank"><img src="../media/{esc(media_id)}" alt="Galeriebild"></a>
              <div class="preview-tile-actions">{action}</div>
            </div>
            """
        )
    reset = (
        f"""
        <form method="post" action="{esc(house_id)}/preview/clear" data-no-loading="true" style="margin-top:10px">
          <button class="secondary" type="submit">Automatische Bildauswahl verwenden</button>
        </form>
        """
        if selected
        else ""
    )
    return f'<div class="preview-grid">{"".join(tiles)}</div>{reset}'


def merge_panel_html(house: dict[str, Any]) -> str:
    house_id = str(house.get("id") or "")
    candidates = [
        item
        for item in list_houses()
        if str(item.get("id") or "") != house_id
        and str(item.get("status") or "new") not in {"rejected", "merged"}
    ]
    if not candidates:
        return ""
    options = []
    for item in candidates:
        source_count = len(list_sources(str(item.get("id") or "")))
        label = f"{item.get('title') or 'Unbenannte Hausakte'} · {item.get('location_text') or 'Lage unbekannt'} · {source_count} Quelle(n)"
        options.append(f'<option value="{esc(item.get("id"))}">{esc(label)}</option>')
    return f"""
    <div class="card compact-card merge-card">
      <details>
        <summary><strong>Zwei Hausakten zusammenlegen</strong></summary>
        <p class="merge-warning"><strong>Diese Hausakte bleibt bestehen.</strong> Die ausgewählte zweite Hausakte wird eingegliedert und danach aus der Übersicht entfernt.</p>
        <p class="muted">Inseratsquellen, Maklerbeschreibungen, Feldnachweise, Bilder, PDFs, Kandidatenzuordnungen und Preisverläufe bleiben erhalten. Doppelte Bilder werden anhand URL beziehungsweise Datei-Hash entfernt. Anschließend wird automatisch eine neue ChatGPT-Analyse angestoßen.</p>
        <form method="post" action="{esc(house_id)}/merge" data-loading="Hausakten werden zusammengeführt und die neue Analyse wird gestartet …" onsubmit="return confirm('Die ausgewählte Hausakte wirklich in diese Hausakte übernehmen?');">
          <label>Zweite Hausakte</label>
          <select name="source_house_id" required><option value="">Bitte auswählen</option>{''.join(options)}</select>
          <button type="submit">Hausakten zusammenlegen</button>
        </form>
      </details>
    </div>
    """


def list_merge_events(house_id: str) -> list[dict[str, Any]]:
    ensure_house_merge_schema()
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM house_merge_events WHERE target_house_id = ? ORDER BY created_at DESC",
            (house_id,),
        ).fetchall()
    return [row_to_dict(row) or {} for row in rows]


def _balanced_analysis_images(house_id: str) -> list[tuple[dict[str, Any], Path]]:
    """Select high-quality images across all brokers instead of filling the limit from one source."""
    house = get_house(house_id) or {}
    selected_id = str(house.get("preview_media_id") or "")
    unique: list[tuple[dict[str, Any], Path]] = []
    seen: set[str] = set()
    for media in list_media(house_id):
        if media.get("kind") != "image" or media.get("download_status") != "downloaded" or not media.get("local_path"):
            continue
        path = Path(str(media.get("local_path")))
        try:
            path.resolve().relative_to(PROJECTS_DIR.resolve())
        except Exception:
            continue
        if not path.exists() or not path.is_file():
            continue
        key = str(media.get("content_hash") or media.get("original_url") or path.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append((media, path))

    selected = [pair for pair in unique if str(pair[0].get("id") or "") == selected_id]
    remaining = [pair for pair in unique if str(pair[0].get("id") or "") != selected_id]
    groups: dict[str, list[tuple[dict[str, Any], Path]]] = {}
    for pair in remaining:
        group = str(pair[0].get("source_id") or "ohne_quelle")
        groups.setdefault(group, []).append(pair)
    for values in groups.values():
        values.sort(key=lambda pair: int(pair[0].get("file_size_bytes") or 0), reverse=True)

    result = selected[:1]
    while groups:
        empty: list[str] = []
        for group, values in list(groups.items()):
            if values:
                result.append(values.pop(0))
            if not values:
                empty.append(group)
        for group in empty:
            groups.pop(group, None)
    return result


def _append_css() -> None:
    if "preview-grid" not in product_ui.PRODUCT_CSS:
        product_ui.PRODUCT_CSS += MERGE_CSS


def _patch_ui() -> None:
    _append_css()
    focused_ui._house_preview = preview_for_dashboard
    product_ui.hero_gallery_html = hero_gallery_html
    product_ui.image_grid_html = preview_image_grid_html
    house_manage.hero_gallery_html = hero_gallery_html
    house_manage.image_grid_html = preview_image_grid_html

    current_edit: Callable[[dict[str, Any]], str] = product_ui.edit_house_form_html
    if not getattr(current_edit, "_merge_panel_patched", False):
        def edit_with_merge(house: dict[str, Any]) -> str:
            events = list_merge_events(str(house.get("id") or ""))
            history = ""
            if events:
                rows = "".join(
                    f"<li>{esc(format_datetime(event.get('created_at')))} · {esc(event.get('source_title') or event.get('source_house_id'))} · {esc(event.get('moved_sources'))} Quelle(n), {esc(event.get('moved_media'))} Medien, {esc(event.get('removed_duplicate_media'))} Duplikat(e)</li>"
                    for event in events[:8]
                )
                history = f'<div class="card compact-card"><details><summary><strong>Zusammenführungsverlauf ({len(events)})</strong></summary><ul>{rows}</ul></details></div>'
            return current_edit(house) + merge_panel_html(house) + history

        setattr(edit_with_merge, "_merge_panel_patched", True)
        product_ui.edit_house_form_html = edit_with_merge

    analysis_package.local_image_paths = _balanced_analysis_images


def register_house_merge(app: FastAPI) -> None:
    global _patched
    if _patched:
        return
    ensure_house_merge_schema()
    _patch_ui()

    @app.post("/houses/{house_id}/preview/clear")
    async def clear_preview(house_id: str) -> RedirectResponse:
        try:
            set_preview_media(house_id, None)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return RedirectResponse(f"../../{house_id}", status_code=303)

    @app.post("/houses/{house_id}/preview/{media_id}")
    async def select_preview(house_id: str, media_id: str) -> RedirectResponse:
        try:
            set_preview_media(house_id, media_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(f"../../{house_id}", status_code=303)

    @app.post("/houses/{house_id}/merge")
    async def merge_house_route(house_id: str, source_house_id: str = Form(...)) -> RedirectResponse:
        try:
            merge_houses(house_id, source_house_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await auto_export_house_to_github(house_id)
        return RedirectResponse(f"../{house_id}", status_code=303)

    _patched = True
