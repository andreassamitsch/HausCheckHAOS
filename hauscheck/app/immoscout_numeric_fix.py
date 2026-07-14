from __future__ import annotations

import math
import re
from typing import Any

from fastapi import FastAPI

import app.house_manage as house_manage
import app.immoscout_dynamic_search as dynamic
import app.immoscout_support as support
import app.modern_ui as modern_ui
from app.storage import connect, now_iso, row_to_dict


_PATCHED = False
MAX_PLAUSIBLE_MIN_LIVING_M2 = 750.0


def clean_form_float(value: object) -> float | None:
    """Parse HTML number-input values without treating a decimal dot as a thousands separator."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None

    text = str(value).strip().replace("\u00a0", "").replace(" ", "").replace("'", "")
    if not text:
        return None
    text = re.sub(r"[^0-9,\.\-+]", "", text)
    if not text or text in {"-", "+", ".", ","}:
        return None

    if "," in text and "." in text:
        decimal_separator = "," if text.rfind(",") > text.rfind(".") else "."
        thousands_separator = "." if decimal_separator == "," else ","
        text = text.replace(thousands_separator, "")
        text = text.replace(decimal_separator, ".")
    elif "," in text:
        if text.count(",") == 1:
            text = text.replace(",", ".")
        else:
            head, tail = text.rsplit(",", 1)
            text = head.replace(",", "") + ("." + tail if len(tail) <= 2 else tail)
    elif "." in text and text.count(".") > 1:
        head, tail = text.rsplit(".", 1)
        text = head.replace(".", "") + ("." + tail if len(tail) <= 2 else tail)

    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _repair_scale(living: float | None) -> float:
    """Return the accidental power-of-ten multiplier introduced by repeated form saves."""
    if living is None or living <= MAX_PLAUSIBLE_MIN_LIVING_M2:
        return 1.0
    factor = 1.0
    candidate = living
    while candidate > MAX_PLAUSIBLE_MIN_LIVING_M2 and candidate / 10.0 >= 10.0:
        candidate /= 10.0
        factor *= 10.0
    return factor if candidate <= MAX_PLAUSIBLE_MIN_LIVING_M2 else 1.0


def repair_corrupted_search_profile_numbers() -> int:
    """Repair profiles affected by the old 700.0 -> 7000.0 conversion bug.

    The same form save multiplied living and plot values by ten. The living-area field
    therefore provides a safe common scale factor for both measurements. Custom URLs are
    never rewritten; only automatically generated portal URLs are refreshed.
    """
    changed = 0
    with connect() as con:
        rows = con.execute("SELECT * FROM search_profiles").fetchall()
        for row in rows:
            profile = row_to_dict(row) or {}
            living = clean_form_float(profile.get("min_living_area_m2"))
            plot = clean_form_float(profile.get("min_plot_area_m2"))
            factor = _repair_scale(living)
            if factor <= 1.0 or living is None:
                continue

            corrected_living = living / factor
            corrected_plot = plot / factor if plot is not None else None
            corrected = dict(profile)
            corrected["min_living_area_m2"] = corrected_living
            corrected["min_plot_area_m2"] = corrected_plot

            fields: dict[str, Any] = {
                "min_living_area_m2": corrected_living,
                "min_plot_area_m2": corrected_plot,
                "updated_at": now_iso(),
                "last_run_status": "Zahlenfehler automatisch korrigiert · Such-URL neu erzeugt",
                "last_error": None,
            }
            if str(profile.get("search_url_mode") or "automatic") == "automatic":
                provider = str(profile.get("source_name") or support.WILLHABEN_SOURCE)
                areas = dynamic._areas_from_profile(corrected)
                if provider == support.IMMOSCOUT_SOURCE:
                    fields["search_url"] = "\n".join(dynamic.build_immoscout_auto_urls(corrected, areas))
                elif provider == support.WILLHABEN_SOURCE:
                    import app.main as main
                    fields["search_url"] = "\n".join(main.build_willhaben_auto_urls(corrected, areas))

            sql = ", ".join(f"{key} = ?" for key in fields)
            con.execute(
                f"UPDATE search_profiles SET {sql} WHERE id = ?",
                list(fields.values()) + [profile["id"]],
            )
            changed += 1
        con.commit()
    return changed


def register_immoscout_numeric_fix(app: FastAPI) -> None:
    global _PATCHED
    if _PATCHED:
        return

    # The modern search-profile routes resolve these module attributes at request time.
    house_manage.clean_float = clean_form_float
    modern_ui.clean_float = clean_form_float
    repair_corrupted_search_profile_numbers()
    _PATCHED = True
