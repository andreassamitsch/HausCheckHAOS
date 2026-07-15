from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import app.media_quality_v2 as media_quality


_PATCHED = False


def ai_image_paths_without_cleanup(house_id: str) -> list[tuple[dict[str, Any], Path]]:
    """Select already-cleaned images without starting another gallery comparison."""
    candidates: list[tuple[dict[str, Any], Path, int]] = []
    for item in media_quality.ordered_image_items(house_id):
        path = Path(str(item.get("local_path") or ""))
        try:
            path.resolve().relative_to(media_quality.PROJECTS_DIR.resolve())
        except Exception:
            continue
        if not path.exists() or not path.is_file():
            continue
        try:
            resized_size = len(media_quality._resized_jpeg_bytes_v2(path))
        except Exception:
            resized_size = int(item.get("file_size_bytes") or path.stat().st_size)
        candidates.append((item, path, resized_size))

    total_count = len(candidates)
    total_bytes = sum(candidate[2] for candidate in candidates)
    mode = "all"
    selected = candidates
    if total_count > media_quality.AI_IMAGE_MAX_COUNT or total_bytes > media_quality.AI_IMAGE_BUDGET_BYTES:
        mode = "balanced_across_full_gallery"
        max_count = min(media_quality.AI_IMAGE_MAX_COUNT, total_count)
        selected = []
        lower_bound = max(11, min(18, max_count))
        for count in range(max_count, lower_bound - 1, -1):
            indices = media_quality._even_indices(total_count, count)
            attempt = [candidates[index] for index in indices]
            if sum(candidate[2] for candidate in attempt) <= media_quality.AI_IMAGE_BUDGET_BYTES:
                selected = attempt
                break
        if not selected:
            selected = []
            used = 0
            for index in media_quality._even_indices(total_count, min(total_count, 18)):
                candidate = candidates[index]
                if selected and used + candidate[2] > media_quality.AI_IMAGE_BUDGET_BYTES:
                    continue
                selected.append(candidate)
                used += candidate[2]

    media_quality._LAST_SELECTION[house_id] = {
        "selection_mode": mode,
        "total_unique_images": total_count,
        "exported_images": len(selected),
        "omitted_images": max(0, total_count - len(selected)),
        "resized_bytes_estimated": sum(candidate[2] for candidate in selected),
        "cleanup_policy": "after_import_or_manual_only",
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


def create_analysis_zip_without_cleanup(house_id: str) -> Path:
    """Build the AI package without re-running perceptual deduplication."""
    if not media_quality._ORIGINAL_CREATE_ZIP:
        raise RuntimeError("Analyseexport ist nicht registriert")

    target = media_quality._ORIGINAL_CREATE_ZIP(house_id)
    selection = dict(
        media_quality._LAST_SELECTION.get(
            house_id,
            {
                "selection_mode": "none",
                "total_unique_images": 0,
                "exported_images": 0,
                "omitted_images": 0,
                "images": [],
            },
        )
    )
    selection["media_cleanup"] = {
        "performed": False,
        "policy": "after_import_or_manual_only",
        "reason": "The gallery was already checked after media import or can be cleaned manually.",
    }
    with zipfile.ZipFile(target, "a", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "image_selection.json",
            json.dumps(selection, ensure_ascii=False, indent=2),
        )
    return target


def register_media_cleanup_policy() -> None:
    global _PATCHED
    if _PATCHED:
        return

    import app.analysis_package as analysis_package
    import app.github_auto_export as github_auto_export
    import app.github_exchange as github_exchange
    import app.gmail_exchange as gmail_exchange

    media_quality.ai_image_paths = ai_image_paths_without_cleanup
    media_quality.create_analysis_zip_v2 = create_analysis_zip_without_cleanup

    analysis_package.local_image_paths = ai_image_paths_without_cleanup
    analysis_package.create_analysis_zip = create_analysis_zip_without_cleanup
    github_auto_export.create_analysis_zip = create_analysis_zip_without_cleanup
    github_exchange.create_analysis_zip = create_analysis_zip_without_cleanup
    gmail_exchange.create_analysis_zip = create_analysis_zip_without_cleanup

    _PATCHED = True
