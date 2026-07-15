from __future__ import annotations

from typing import Any

from fastapi import FastAPI

import app.product_ui as product_ui
import app.valuation_ui as valuation_ui
from app.analysis_package import load_analysis
from app.pipeline_status import get_pipeline_status
from app.ui_helpers import esc, format_datetime


_PATCHED = False


def _analysis_waiting_detail(status: dict[str, Any]) -> str:
    previous = status.get("analysis_imported_at") or status.get("analysis_date")
    exported = status.get("exported_at")
    previous_text = format_datetime(previous, "Zeitpunkt unbekannt")
    exported_text = format_datetime(exported, "Zeitpunkt unbekannt")
    return f"Vorherige Analyse: {previous_text} · neues Ergebnis seit {exported_text} ausstehend"


def pipeline_card_html(house_id: str) -> str:
    status = get_pipeline_status(house_id)
    analysis_done = bool(status.get("analysis_current"))
    analysis_stale = bool(status.get("analysis_stale"))
    source_done = int(status.get("source_count") or 0) > 0
    media_done = int(status.get("downloaded_count") or 0) > 0 and int(status.get("pending_count") or 0) == 0
    exported = bool(status.get("exported_at"))
    failed = int(status.get("failed_count") or 0)
    state_error = str(status.get("state") or "") == "error"

    if analysis_done:
        analysis_detail = format_datetime(status.get("analysis_imported_at"), "Analyse importiert")
    elif analysis_stale and exported:
        analysis_detail = _analysis_waiting_detail(status)
    else:
        analysis_detail = "Ergebnis wird automatisch übernommen" if exported else "wartet auf Export"

    steps = [
        valuation_ui._pipeline_step(
            "Inserat erfasst",
            source_done,
            not source_done,
            f"{status.get('source_count', 0)} Quelle(n) gespeichert",
        ),
        valuation_ui._pipeline_step(
            "Medien geladen",
            media_done,
            source_done and not media_done,
            f"{status.get('downloaded_count', 0)} geladen · {status.get('pending_count', 0)} offen · {failed} Fehler",
            error=failed > 0 and not media_done,
        ),
        valuation_ui._pipeline_step(
            "Zur Analyse bereitgestellt",
            exported,
            media_done and not exported,
            format_datetime(status.get("exported_at"), "ZIP wird nach GitHub exportiert"),
            error=state_error and not exported,
        ),
        valuation_ui._pipeline_step(
            "ChatGPT-Analyse importiert",
            analysis_done,
            exported and not analysis_done and not state_error,
            analysis_detail,
            error=state_error and exported and not analysis_done,
        ),
    ]
    warning_html = ""
    if analysis_stale:
        warning_html = (
            "<div class='subtle-box' data-analysis-freshness='stale'>"
            "<strong>Neue KI-Analyse läuft.</strong> "
            "Die unten angezeigte Bewertung stammt noch vom vorherigen Lauf und wird nach dem Rückimport automatisch ersetzt."
            "</div>"
        )
    error_html = (
        f"<p class='danger'><strong>Letzter Fehler:</strong> {esc(status.get('last_error'))}</p>"
        if status.get("last_error")
        else ""
    )
    return f"""
    <div class="card">
      <h2>Verarbeitungsstatus</h2>
      <p>{product_ui._pipeline_badge(status)}<span class="pill">aktualisiert: {esc(format_datetime(status.get('updated_at')))}</span></p>
      {warning_html}
      <div class="status-steps">{''.join(steps)}</div>
      {error_html}
      <form method="post" action="{esc(house_id)}/analysis/retry" data-loading="Analysepaket wird erneut bereitgestellt …">
        <button type="submit">Analyse erneut anstoßen</button>
      </form>
    </div>
    """


def analysis_card_html(house_id: str) -> str:
    analysis = load_analysis(house_id)
    if not analysis:
        return """
        <div class="card">
          <h2>KI-Bewertung, Kaufpreis und Investitionen</h2>
          <p class="muted">Noch kein Ergebnis vorhanden. Nach dem Import ersetzt der KI-Score die vorläufige Datenbewertung.</p>
        </div>
        """

    status = get_pipeline_status(house_id)
    stale = bool(status.get("analysis_stale"))
    positives = analysis.get("positive_findings") or []
    risks = analysis.get("risk_findings") or []
    positive_html = "".join(f"<li>{esc(item)}</li>" for item in positives[:8]) or "<li class='muted'>Keine Chancen eingetragen.</li>"
    risk_html = "".join(f"<li>{esc(item)}</li>" for item in risks[:8]) or "<li class='muted'>Keine Risiken eingetragen.</li>"

    heading = "Vorherige KI-Bewertung – neue Analyse ausstehend" if stale else "KI-Bewertung, Kaufpreis und Investitionen"
    score_class = "warn" if stale else "good"
    freshness_html = ""
    if stale:
        freshness_html = f"""
        <div class="subtle-box" data-analysis-freshness="stale">
          <strong>Dieser Text ist noch die vorherige Analyse.</strong>
          <p>Das neue Analysepaket wurde am {esc(format_datetime(status.get('exported_at')))} bereitgestellt. Bis das neue Ergebnis importiert ist, bleibt die alte Bewertung nur als Vergleich sichtbar.</p>
        </div>
        """

    imported_pill = ""
    if status.get("analysis_imported_at"):
        imported_pill = f"<span class='pill'>importiert: {esc(format_datetime(status.get('analysis_imported_at')))}</span>"

    return f"""
    <div class="card" data-analysis-current="{'false' if stale else 'true'}">
      <h2>{heading}</h2>
      {freshness_html}
      <p><span class="pill {score_class}">Gesamtbewertung {esc(analysis.get('new_score'))}/100</span><span class="pill">Sicherheit: {esc(analysis.get('confidence'))}</span><span class="pill">Analyse: {esc(format_datetime(analysis.get('analysis_date')))}</span>{imported_pill}</p>
      <p>{esc(analysis.get('summary') or '')}</p>
      <p><strong>Empfehlung:</strong> {esc(analysis.get('recommendation') or '')}</p>
      {valuation_ui._price_assessment_html(analysis)}
      {valuation_ui._investment_html(analysis)}
      <div class="grid"><div><strong>Chancen</strong><ul>{positive_html}</ul></div><div><strong>Risiken</strong><ul>{risk_html}</ul></div></div>
    </div>
    """


def register_analysis_freshness_ui(app: FastAPI) -> None:
    del app
    global _PATCHED
    if _PATCHED:
        return
    product_ui.pipeline_card_html = pipeline_card_html
    product_ui.analysis_card_html = analysis_card_html
    _PATCHED = True
