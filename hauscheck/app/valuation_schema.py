from __future__ import annotations

from typing import Any, Callable

import app.analysis_package as analysis_package


_patched = False


def _enhanced_schema(original: Callable[[str], dict[str, Any]], house_id: str) -> dict[str, Any]:
    schema = original(house_id)
    properties = schema.setdefault("properties", {})
    properties["price_assessment"] = {
        "type": "object",
        "description": "Grobe Kaufpreiseinschätzung aus Inseratsdaten, sichtbarem Zustand und erkennbarem Investitionsbedarf; kein Verkehrswertgutachten.",
        "properties": {
            "asking_price_eur": {"type": ["integer", "null"]},
            "fair_value_low_eur": {"type": ["integer", "null"]},
            "fair_value_high_eur": {"type": ["integer", "null"]},
            "suggested_first_offer_eur": {"type": ["integer", "null"]},
            "suggested_target_price_eur": {"type": ["integer", "null"]},
            "maximum_recommended_price_eur": {"type": ["integer", "null"]},
            "confidence": {"enum": ["niedrig", "mittel", "hoch"]},
            "reasoning": {"type": "string"},
        },
    }
    properties["investment_items"] = {
        "type": "array",
        "description": "Erkennbare oder aus dem Inserat ableitbare Investitionsposten. Unsichere Maßnahmen klar kennzeichnen.",
        "items": {
            "type": "object",
            "properties": {
                "category": {"type": "string"},
                "measure": {"type": "string"},
                "priority": {"enum": ["sofort", "kurzfristig", "mittelfristig", "optional", "unklar"]},
                "low_eur": {"type": ["integer", "null"]},
                "high_eur": {"type": ["integer", "null"]},
                "confidence": {"enum": ["niedrig", "mittel", "hoch"]},
                "basis": {"type": "string"},
            },
        },
    }
    properties["estimated_total_cost_eur"] = {
        "type": "object",
        "description": "Grobe Summe aus empfohlenem Zielkaufpreis und Investitionen; Kaufnebenkosten, Finanzierung und Steuern standardmäßig nicht enthalten.",
        "properties": {
            "low": {"type": ["integer", "null"]},
            "high": {"type": ["integer", "null"]},
            "confidence": {"enum": ["niedrig", "mittel", "hoch"]},
            "includes_purchase_price": {"type": "boolean"},
            "includes_acquisition_costs": {"type": "boolean"},
            "comment": {"type": "string"},
        },
    }
    return schema


def _enhanced_prompt(original: Callable[[str], str], house_id: str) -> str:
    return original(house_id) + """

## Hauptbewertung, Kaufpreis und Investitionen

Der `new_score` ist nach der Analyse die maßgebliche HausCheck-Gesamtbewertung und ersetzt die rein regelbasierte Vorprüfung. Begründe ihn anhand der gesicherten Inseratsdaten, der tatsächlich sichtbaren Bildbefunde, des Modernisierungsstands, des Energiezustands und des erwartbaren Investitionsbedarfs.

Ergänze außerdem, soweit anhand der vorhandenen Daten vertretbar:

- `price_assessment`: grobe Kaufpreiseinschätzung mit fairem Bereich, sinnvollem ersten Angebot, realistischem Zielpreis und maximal empfohlenem Preis.
- `investment_items`: einzelne erkennbare oder plausibel notwendige Maßnahmen mit Kategorie, Priorität, Kostenspanne, Sicherheit und Grundlage.
- `estimated_investment_eur`: Summe der wahrscheinlichen Investitionen. Vermeide Scheingenauigkeit und bilde eine realistische Bandbreite.
- `estimated_total_cost_eur`: empfohlener Zielkaufpreis plus Investitionsbandbreite. Kaufnebenkosten, Finanzierung und Steuern nur einbeziehen, wenn dies ausdrücklich dokumentiert ist; sonst `includes_acquisition_costs` auf `false` setzen.

Wichtige Regeln:

- Ohne belastbare Vergleichsobjekte ist die Kaufpreiseinschätzung keine Marktwert- oder Verkehrswertermittlung.
- Nicht sichtbare Bauteile, Leitungen, Statik, Abdichtung und Genehmigungslage nicht als gesichert behandeln.
- Kosten nur angeben, wenn eine Maßnahme aus Daten oder Bildern ableitbar ist; sonst `null` beziehungsweise niedrige Sicherheit verwenden.
- KI-generierte Renderings, Werbegrafiken und historische Bilder nicht als Zustandsnachweis verwenden.
- Der vorgeschlagene Maximalpreis soll den sichtbaren Zustand, die Unsicherheiten und den Investitionsbedarf berücksichtigen, nicht nur den Angebotspreis.
"""


def register_valuation_schema() -> None:
    global _patched
    if _patched:
        return

    original_schema = analysis_package.analysis_schema
    original_prompt = analysis_package.readme_prompt

    def schema(house_id: str) -> dict[str, Any]:
        return _enhanced_schema(original_schema, house_id)

    def prompt(house_id: str) -> str:
        return _enhanced_prompt(original_prompt, house_id)

    analysis_package.analysis_schema = schema
    analysis_package.readme_prompt = prompt

    # Module mit direkt importierter Schema-Funktion ebenfalls auf den erweiterten Stand bringen.
    try:
        import app.github_b64_export as github_b64_export

        github_b64_export.analysis_schema = schema
    except Exception:
        pass

    _patched = True
