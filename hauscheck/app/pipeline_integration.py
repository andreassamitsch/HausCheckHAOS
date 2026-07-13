from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI

import app.analysis_package as analysis_package
import app.github_exchange as github_exchange
from app.pipeline_status import set_pipeline_stage


_patched = False


def _wrap_save_analysis(original: Callable[[str, dict[str, Any]], Path]) -> Callable[[str, dict[str, Any]], Path]:
    def wrapped(house_id: str, data: dict[str, Any]) -> Path:
        target = original(house_id, data)
        set_pipeline_stage(
            house_id,
            "completed",
            "ok",
            "ChatGPT-Analyse wurde automatisch importiert.",
        )
        return target

    return wrapped


def register_pipeline_integration(app: FastAPI) -> None:
    del app  # Registrierung dient der Initialisierungsreihenfolge.
    global _patched
    if _patched:
        return

    original = analysis_package.save_analysis
    wrapped = _wrap_save_analysis(original)
    analysis_package.save_analysis = wrapped
    # github_exchange hat save_analysis bereits direkt importiert; deshalb dort ebenfalls ersetzen.
    github_exchange.save_analysis = wrapped
    _patched = True
