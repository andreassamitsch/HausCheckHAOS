from __future__ import annotations

from typing import Any

from fastapi import FastAPI

import app.media_quality_v2 as media_quality


_PATCHED = False


def _startup_cleanup_disabled() -> dict[str, Any]:
    """Do not scan existing galleries automatically during or after startup."""
    return {
        "houses": 0,
        "removed": 0,
        "errors": [],
        "disabled": True,
        "policy": "after_import_or_manual_only",
    }


def register_media_startup_fix(app: FastAPI) -> None:
    global _PATCHED
    if _PATCHED:
        return

    # register_media_quality_v2() still invokes cleanup_all_houses() while registering.
    # Keep that legacy call harmless. Media cleanup is performed only after a completed
    # media download or through the visible manual action in a house record.
    media_quality.cleanup_all_houses = _startup_cleanup_disabled
    _PATCHED = True
