from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

import app.media_quality_v2 as media_quality


_PATCHED = False
_ORIGINAL_FINGERPRINT = media_quality._fingerprint
_RESAMPLE = getattr(Image, "Resampling", Image).LANCZOS


def _color_vector(image: Image.Image, size: int = 8) -> list[int]:
    pixels = image.convert("RGB").resize((size, size), _RESAMPLE).getdata()
    return [channel for pixel in pixels for channel in pixel]


def _crop_images(image: Image.Image) -> list[Image.Image]:
    """Create compact crop variants for resized, cropped and slightly shifted broker photos."""
    result: list[Image.Image] = [image]
    width, height = image.size

    # Typical symmetric portal crops.
    for inset in (0.03, 0.05, 0.08, 0.12):
        margin_x = int(width * inset)
        margin_y = int(height * inset)
        if width - margin_x * 2 >= 32 and height - margin_y * 2 >= 32:
            result.append(image.crop((margin_x, margin_y, width - margin_x, height - margin_y)))

    # Slightly shifted camera/framing variants. A single scale keeps the signature compact.
    fraction = 0.82
    crop_width = int(width * fraction)
    crop_height = int(height * fraction)
    for anchor_x, anchor_y in (
        (0.0, 0.0), (0.5, 0.0), (1.0, 0.0),
        (0.0, 0.5), (0.5, 0.5), (1.0, 0.5),
        (0.0, 1.0), (0.5, 1.0), (1.0, 1.0),
    ):
        left = int((width - crop_width) * anchor_x)
        top = int((height - crop_height) * anchor_y)
        result.append(image.crop((left, top, left + crop_width, top + crop_height)))
    return result


def fingerprint_scene_aware(path: Path, media: dict[str, Any]) -> dict[str, Any] | None:
    result = _ORIGINAL_FINGERPRINT(path, media)
    if not result:
        return None
    try:
        with Image.open(path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            variants = _crop_images(image)
            result["crop_vectors"] = [media_quality._gray_vector(item, 12) for item in variants]
            result["crop_hashes"] = [media_quality._dhash(item) for item in variants]
            result["crop_ahashes"] = [media_quality._ahash(item) for item in variants]
            result["crop_color_vectors"] = [_color_vector(item) for item in variants]
    except (UnidentifiedImageError, OSError, ValueError):
        result["crop_vectors"] = []
        result["crop_hashes"] = []
        result["crop_ahashes"] = []
        result["crop_color_vectors"] = []

    # The more tolerant scene comparison is intentionally allowed only across different sources.
    result["source_id"] = str(media.get("source_id") or "")
    result["source_name"] = str(media.get("source_name") or "")
    return result


def _color_mad(left: list[int], right: list[int]) -> float:
    if not left or len(left) != len(right) or len(left) % 3:
        return 999.0
    pixel_count = len(left) // 3
    left_means = [sum(left[index] for index in range(channel, len(left), 3)) / pixel_count for channel in range(3)]
    right_means = [sum(right[index] for index in range(channel, len(right), 3)) / pixel_count for channel in range(3)]
    return sum(
        abs((left[index] - left_means[index % 3]) - (right[index] - right_means[index % 3]))
        for index in range(len(left))
    ) / len(left)


def _best_crop_alignment(left: dict[str, Any], right: dict[str, Any]) -> dict[str, float | int]:
    left_vectors = list(left.get("crop_vectors") or [])
    right_vectors = list(right.get("crop_vectors") or [])
    left_hashes = list(left.get("crop_hashes") or [])
    right_hashes = list(right.get("crop_hashes") or [])
    left_ahashes = list(left.get("crop_ahashes") or [])
    right_ahashes = list(right.get("crop_ahashes") or [])
    left_colors = list(left.get("crop_color_vectors") or [])
    right_colors = list(right.get("crop_color_vectors") or [])

    best: dict[str, float | int] = {
        "score": 999.0,
        "gray_distance": 999.0,
        "color_distance": 999.0,
        "dhash_distance": 999,
        "ahash_distance": 999,
    }
    for left_index, left_vector in enumerate(left_vectors):
        if left_index >= len(left_hashes) or left_index >= len(left_ahashes) or left_index >= len(left_colors):
            continue
        for right_index, right_vector in enumerate(right_vectors):
            if right_index >= len(right_hashes) or right_index >= len(right_ahashes) or right_index >= len(right_colors):
                continue
            gray_distance = media_quality._normalized_mad(left_vector, right_vector)
            color_distance = _color_mad(left_colors[left_index], right_colors[right_index])
            dhash_distance = media_quality._hash_distance(left_hashes[left_index], right_hashes[right_index])
            ahash_distance = media_quality._hash_distance(left_ahashes[left_index], right_ahashes[right_index])
            score = gray_distance + color_distance * 0.6 + dhash_distance * 0.35 + ahash_distance * 0.2
            if score < float(best["score"]):
                best = {
                    "score": score,
                    "gray_distance": gray_distance,
                    "color_distance": color_distance,
                    "dhash_distance": dhash_distance,
                    "ahash_distance": ahash_distance,
                }
    return best


def visual_duplicate_scene_aware(
    left: dict[str, Any],
    right: dict[str, Any],
) -> tuple[bool, str, dict[str, Any]]:
    if left.get("content_hash") and left.get("content_hash") == right.get("content_hash"):
        return True, "exact_hash", {"content_hash": left.get("content_hash")}

    left_ratio = float(left.get("width") or 1) / max(1.0, float(left.get("height") or 1))
    right_ratio = float(right.get("width") or 1) / max(1.0, float(right.get("height") or 1))
    ratio_delta = abs(math.log(max(0.0001, left_ratio / right_ratio)))
    dhash_distance = media_quality._hash_distance(left.get("dhash"), right.get("dhash"))
    ahash_distance = media_quality._hash_distance(left.get("ahash"), right.get("ahash"))
    center_distance = media_quality._hash_distance(left.get("center_hash"), right.get("center_hash"))
    pixel_distance = media_quality._normalized_mad(left.get("vector") or [], right.get("vector") or [])
    center_pixel_distance = media_quality._normalized_mad(
        left.get("center_vector") or [], right.get("center_vector") or []
    )
    histogram_distance = media_quality._histogram_distance(
        left.get("histogram") or [], right.get("histogram") or []
    )
    alignment = _best_crop_alignment(left, right)

    details: dict[str, Any] = {
        "ratio_delta": round(ratio_delta, 4),
        "dhash_distance": dhash_distance,
        "ahash_distance": ahash_distance,
        "center_distance": center_distance,
        "pixel_distance": round(pixel_distance, 3),
        "center_pixel_distance": round(center_pixel_distance, 3),
        "histogram_distance": round(histogram_distance, 4),
        "crop_score": round(float(alignment["score"]), 3),
        "crop_gray_distance": round(float(alignment["gray_distance"]), 3),
        "crop_color_distance": round(float(alignment["color_distance"]), 3),
        "crop_dhash_distance": int(alignment["dhash_distance"]),
        "crop_ahash_distance": int(alignment["ahash_distance"]),
    }

    # Re-encoding and pure resizing preserve both luminance distribution and structure.
    same_frame = (
        ratio_delta <= 0.06
        and dhash_distance <= 6
        and ahash_distance <= 6
        and pixel_distance <= 9.0
        and histogram_distance <= 0.14
    )
    recompressed = (
        ratio_delta <= 0.06
        and dhash_distance <= 8
        and ahash_distance <= 8
        and pixel_distance <= 7.5
        and histogram_distance <= 0.10
    )
    mildly_cropped = (
        ratio_delta <= 0.18
        and float(alignment["gray_distance"]) <= 8.0
        and float(alignment["color_distance"]) <= 9.0
        and int(alignment["dhash_distance"]) <= 7
        and int(alignment["ahash_distance"]) <= 8
        and histogram_distance <= 0.15
    )

    left_source = str(left.get("source_id") or "")
    right_source = str(right.get("source_id") or "")
    cross_source = bool(left_source and right_source and left_source != right_source)
    # Different brokers often use a second shot of the same room with a small camera shift or
    # changed towel/chair. Remove that redundant scene only across sources, never within one gallery.
    same_scene_cross_source = (
        cross_source
        and ratio_delta <= 0.18
        and float(alignment["score"]) <= 31.0
        and float(alignment["gray_distance"]) <= 16.5
        and float(alignment["color_distance"]) <= 13.0
        and int(alignment["dhash_distance"]) <= 16
        and int(alignment["ahash_distance"]) <= 12
        and histogram_distance <= 0.14
    )

    if same_frame:
        return True, "visual_same_frame", details
    if recompressed:
        return True, "visual_recompressed", details
    if mildly_cropped:
        return True, "visual_mild_crop", details
    if same_scene_cross_source:
        details["cross_source"] = True
        details["left_source"] = left_source
        details["right_source"] = right_source
        return True, "cross_source_same_scene", details
    return False, "", details


def register_media_quality_v2_fix() -> None:
    global _PATCHED
    if _PATCHED:
        return
    # Forces every existing image to receive the new scene-aware fingerprint on next cleanup.
    media_quality.DEDUPE_VERSION = 4
    media_quality._fingerprint = fingerprint_scene_aware
    media_quality._visual_duplicate = visual_duplicate_scene_aware
    _PATCHED = True
