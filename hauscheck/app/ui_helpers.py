from __future__ import annotations

import html
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


OPTIONS_PATH = Path("/data/options.json")


def esc(value: object) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def _display_timezone_name() -> str:
    env = str(os.environ.get("HAUSCHECK_DISPLAY_TIMEZONE") or "").strip()
    if env:
        return env
    if OPTIONS_PATH.exists():
        try:
            data = json.loads(OPTIONS_PATH.read_text(encoding="utf-8"))
            configured = str(data.get("display_timezone") or "").strip()
            if configured:
                return configured
        except Exception:
            pass
    return "Europe/Vienna"


def format_datetime(value: object, fallback: str = "–") -> str:
    if value in (None, ""):
        return fallback
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    try:
        target_tz = ZoneInfo(_display_timezone_name())
    except Exception:
        target_tz = ZoneInfo("Europe/Vienna")
    return parsed.astimezone(target_tz).strftime("%d.%m.%Y %H:%M")


def format_eur(value: object, fallback: str = "–") -> str:
    if value in (None, ""):
        return fallback
    try:
        number = int(round(float(value)))
    except Exception:
        return str(value)
    return f"{number:,}".replace(",", ".") + " €"


def value_float(data: dict[str, Any], key: str) -> float | None:
    value = data.get(key)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def score_label(score: int) -> dict[str, str]:
    if score >= 82:
        return {"label": "sehr interessant", "pill": "good"}
    if score >= 68:
        return {"label": "interessant", "pill": "good"}
    if score >= 50:
        return {"label": "prüfen", "pill": "warn"}
    return {"label": "kritisch", "pill": "bad"}


def score_property(data: dict[str, Any], status: str = "new") -> dict[str, Any]:
    score = 55
    reasons: list[str] = []
    known = 0

    price = value_float(data, "price_eur")
    living = value_float(data, "living_area_m2")
    plot = value_float(data, "plot_area_m2")
    hwb = value_float(data, "energy_hwb")

    if status == "filtered":
        score -= 25
        reasons.append("harte Filterregel verletzt")
    elif status == "review":
        score -= 8
        reasons.append("manuelle Prüfung nötig")
    elif status == "imported":
        score += 2

    if price is None:
        reasons.append("Preis fehlt")
    else:
        known += 1
        if price <= 320000:
            score += 14
            reasons.append("Preis sehr attraktiv")
        elif price <= 380000:
            score += 8
            reasons.append("Preis im Zielbereich")
        elif price <= 400000:
            score += 1
            reasons.append("Preis an der Obergrenze")
        else:
            score -= 18
            reasons.append("Preis über Zielbereich")

    if living is None:
        reasons.append("Wohnfläche fehlt")
    else:
        known += 1
        if living >= 160:
            score += 12
            reasons.append("große Wohnfläche")
        elif living >= 130:
            score += 8
            reasons.append("Wohnfläche gut")
        elif living >= 120:
            score += 2
            reasons.append("Wohnfläche ausreichend")
        else:
            score -= 18
            reasons.append("Wohnfläche eher knapp")

    if plot is None:
        reasons.append("Grundstück fehlt")
    else:
        known += 1
        if plot >= 1200:
            score += 12
            reasons.append("sehr großes Grundstück")
        elif plot >= 900:
            score += 9
            reasons.append("großes Grundstück")
        elif plot >= 700:
            score += 5
            reasons.append("Grundstück im Wunschbereich")
        elif plot >= 500:
            score -= 1
            reasons.append("Grundstück eher klein")
        else:
            score -= 10
            reasons.append("Grundstück deutlich klein")

    if hwb is None:
        reasons.append("HWB fehlt")
    else:
        known += 1
        if hwb <= 80:
            score += 12
            reasons.append("sehr guter HWB")
        elif hwb <= 150:
            score += 6
            reasons.append("brauchbarer HWB")
        elif hwb <= 250:
            score -= 5
            reasons.append("HWB prüfen")
        elif hwb <= 300:
            score -= 12
            reasons.append("HWB kritisch")
        else:
            score -= 22
            reasons.append("HWB sehr kritisch")

    score = max(0, min(100, int(round(score))))
    label_data = score_label(score)
    confidence = "hoch" if known >= 4 else "mittel" if known >= 2 else "niedrig"
    return {
        "score": score,
        "label": label_data["label"],
        "pill": label_data["pill"],
        "confidence": confidence,
        "reasons": reasons[:4],
    }


def score_html_from_data(data: dict[str, Any], status: str = "new") -> str:
    result = score_property(data, status)
    score = int(result["score"])
    reasons = " · ".join(esc(reason) for reason in result["reasons"])
    return f"""
    <div class="score-box">
      <div class="score-head">
        <span class="score-value">{score}/100</span>
        <span class="pill {esc(result['pill'])}">{esc(result['label'])}</span>
      </div>
      <div class="score-bar"><div class="score-fill" style="width:{score}%"></div></div>
      <div class="score-reasons">Bewertungssicherheit: {esc(result['confidence'])}<br>{reasons}</div>
    </div>
    """


def candidate_score_html(candidate: dict[str, Any], status: str = "new") -> str:
    return score_html_from_data(candidate, status)


def house_score_result(house: dict[str, Any]) -> dict[str, Any]:
    rule = score_property(house, str(house.get("status") or "new"))
    house_id = str(house.get("id") or "")
    analysis: dict[str, Any] | None = None
    if house_id:
        try:
            from app.analysis_package import load_analysis

            analysis = load_analysis(house_id)
        except Exception:
            analysis = None

    if analysis and analysis.get("new_score") not in (None, ""):
        try:
            ai_score = max(0, min(100, int(round(float(analysis["new_score"])))))
        except Exception:
            ai_score = int(rule["score"])
        label_data = score_label(ai_score)
        return {
            "score": ai_score,
            "label": label_data["label"],
            "pill": label_data["pill"],
            "confidence": analysis.get("confidence") or "unbekannt",
            "source": "ai",
            "reasoning": analysis.get("score_reasoning") or analysis.get("summary") or "KI-Auswertung aus Inseratsdaten und Bildern.",
            "rule": rule,
        }

    return {
        **rule,
        "source": "rule",
        "reasoning": "Vorläufige Datenbewertung. Nach der Bildanalyse ersetzt der KI-Score diese Hauptbewertung.",
        "rule": rule,
    }


def house_score_html(house: dict[str, Any]) -> str:
    result = house_score_result(house)
    score = int(result["score"])
    rule = result["rule"]
    if result["source"] == "ai":
        detail = f"KI-Gesamtbewertung · Sicherheit: {esc(result['confidence'])}<br>{esc(result['reasoning'])}"
        rule_details = f"""
        <details>
          <summary>Daten-Vorprüfung: {esc(rule['score'])}/100</summary>
          <div class="score-reasons">{' · '.join(esc(reason) for reason in rule['reasons'])}</div>
        </details>
        """
    else:
        detail = f"Vorläufige Datenbewertung · Sicherheit: {esc(result['confidence'])}<br>{esc(result['reasoning'])}"
        rule_details = ""
    return f"""
    <div class="score-box">
      <div class="score-head">
        <span class="score-value">{score}/100</span>
        <span class="pill {esc(result['pill'])}">{esc(result['label'])}</span>
      </div>
      <div class="score-bar"><div class="score-fill" style="width:{score}%"></div></div>
      <div class="score-reasons">{detail}</div>
      {rule_details}
    </div>
    """
