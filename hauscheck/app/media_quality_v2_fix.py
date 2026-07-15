from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

import app.media_quality_v2 as media_quality


_PATCHED = False
_ORIGINAL_FINGERPRINT = media_quality._fingerprint


def _crop_variants(image: Image.Image) -> tuple[list[list[int]], list[str]]:
    vectors: list[list[int]] = []
    hashes: list[str] = []
    width, height = image.size
    for inset in (0.03, 0.05, 0.08, 0.12):
        margin_x = int(width * inset)
        margin_y = int(height * inset)
        if width - margin_x * 2 < 32 or height - margin_y * 2 < 32:
            continue
        cropped = image.crop((margin_x, margin_y, width - margin_x, height - margin_y))
        vectors.append(media_quality._gray_vector(cropped))
        hashes.append(media_quality._dhash(cropped))
    return vectors, hashes


def fingerprint_crop_aware(path: Path, media: dict[str, Any]) -> dict[str, Any] | None:
    result = _ORIGINAL_FINGERPRINT(path, media)
    if not result:
        return None
    try:
        with Image.open(path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            crop_vectors, crop_hashes = _crop_variants(image)
            result["crop_vectors"] = crop_vectors
            result["crop_hashes"] = crop_hashes
    except (UnidentifiedImageError, OSError, ValueError):
        result["crop_vectors"] = []
        result["crop_hashes"] = []
    return result


def _minimum_crop_distance(left: dict[str, Any], right: dict[str, Any]) -> tuple[float, int]:
    left_full = left.get("vector") or []
    right_full = right.get("vector") or []
    left_vectors = list(left.get("crop_vectors") or [])
    right_vectors = list(right.get("crop_vectors") or [])
    left_hashes = list(left.get("crop_hashes") or [])
    right_hashes = list(right.get("crop_hashes") or [])

    distances: list[float] = []
    hash_distances: list[int] = []
    for vector, image_hash in zip(left_vectors, left_hashes):
        distances.append(media_quality._normalized_mad(vector, right_full))
        hash_distances.append(media_quality._hash_distance(image_hash, right.get("dhash")))
    for vector, image_hash in zip(right_vectors, right_hashes):
        distances.append(media_quality._normalized_mad(vector, left_full))
        hash_distances.append(media_quality._hash_distance(image_hash, left.get("dhash")))
    for left_vector, left_hash in zip(left_vectors, left_hashes):
        for right_vector, right_hash in zip(right_vectors, right_hashes):
            distances.append(media_quality._normalized_mad(left_vector, right_vector))
            hash_distances.append(media_quality._hash_distance(left_hash, right_hash))
    return (min(distances) if distances else 999.0, min(hash_distances) if hash_distances else 999)


def visual_duplicate_conservative(
    left: dict[str, Any],
    right: dict[str, Any],
) -> tuple[bool, str, dict[str, Any]]:
    if left.get("content_hash") and left.get("content_hash") == right.get("content_hash"):
        return True, "exact_hash", {"content_hash": left.get("content_hash")}

    left_ratio = float(left.get("width") or 1) / max(1.0, float(left.get("height") or 1))
    right_ratio = float(right.get("width") or 1) / max(1.0, float(right.get("height") or 1))
    import math

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
    crop_pixel_distance, crop_hash_distance = _minimum_crop_distance(left, right)

    details = {
        "ratio_delta": round(ratio_delta, 4),
        "dhash_distance": dhash_distance,
        "ahash_distance": ahash_distance,
        "center_distance": center_distance,
        "pixel_distance": round(pixel_distance, 3),
        "center_pixel_distance": round(center_pixel_distance, 3),
        "histogram_distance": round(histogram_distance, 4),
        "crop_pixel_distance": round(crop_pixel_distance, 3),
        "crop_hash_distance": crop_hash_distance,
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
    # A small crop may shift normal hashes, therefore compare several symmetric crop variants.
    mildly_cropped = (
        ratio_delta <= 0.18
        and crop_hash_distance <= 6
        and crop_pixel_distance <= 8.0
        and histogram_distance <= 0.15
        and min(dhash_distance, ahash_distance, center_distance) <= 14
    )

    if same_frame:
        return True, "visual_same_frame", details
    if recompressed:
        return True, "visual_recompressed", details
    if mildly_cropped:
        return True, "visual_mild_crop", details
    return False, "", details


def register_media_quality_v2_fix() -> None:
    global _PATCHED
    if _PATCHED:
        return
    media_quality.DEDUPE_VERSION = 3
    media_quality._fingerprint = fingerprint_crop_aware
    media_quality._visual_duplicate = visual_duplicate_conservative
    _PATCHED = True
