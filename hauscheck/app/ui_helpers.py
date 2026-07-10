from __future__ import annotations

import html
from typing import Any


def esc(value: object) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def value_float(data: dict[str, Any], key: str) -> float | None:
    value = data.get(key)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


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
    if score >= 82:
        label = "sehr interessant"
        pill = "good"
    elif score >= 68:
        label = "interessant"
        pill = "good"
    elif score >= 50:
        label = "prüfen"
        pill = "warn"
    else:
        label = "kritisch"
        pill = "bad"

    confidence = "hoch" if known >= 4 else "mittel" if known >= 2 else "niedrig"
    return {"score": score, "label": label, "pill": pill, "confidence": confidence, "reasons": reasons[:4]}


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


def house_score_html(house: dict[str, Any]) -> str:
    return score_html_from_data(house, str(house.get("status") or "new"))
