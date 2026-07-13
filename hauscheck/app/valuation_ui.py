from __future__ import annotations

from typing import Any

from fastapi import FastAPI

import app.dashboard_automation_ui as dashboard_automation_ui
import app.product_ui as product_ui
import app.search_automation_ui as search_automation_ui
from app.analysis_package import load_analysis
from app.pipeline_status import get_pipeline_status, list_pipeline_events
from app.storage import list_evidence, list_media, list_sources
from app.ui_helpers import esc, format_datetime, format_eur


LOCAL_TIME_SCRIPT = r"""
<script>
(() => {
  if (window.__hauscheckLocalTimeInstalled) return;
  window.__hauscheckLocalTimeInstalled = true;
  const iso = /\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?/g;
  const formatter = new Intl.DateTimeFormat('de-AT', {
    timeZone: 'Europe/Vienna', day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: false
  });
  const convert = (text) => text.replace(iso, (raw) => {
    const value = new Date(raw);
    return Number.isNaN(value.getTime()) ? raw : formatter.format(value).replace(',', '');
  });
  const run = () => {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const tag = node.parentElement?.tagName || '';
        return ['SCRIPT', 'STYLE', 'TEXTAREA', 'INPUT'].includes(tag) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
      }
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach((node) => { if (iso.test(node.nodeValue || '')) node.nodeValue = convert(node.nodeValue || ''); iso.lastIndex = 0; });
  };
  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', run) : run();
})();
</script>
"""


def _money_range(low: object, high: object) -> str:
    if low in (None, "") and high in (None, ""):
        return "–"
    if low not in (None, "") and high not in (None, ""):
        return f"{format_eur(low)} bis {format_eur(high)}"
    return format_eur(low if low not in (None, "") else high)


def _pipeline_step(label: str, done: bool, active: bool, detail: str, error: bool = False) -> str:
    css = "error" if error else "done" if done else "active" if active else ""
    icon = "!" if error else "✓" if done else "…" if active else "·"
    return f"<div class='status-step {css}'><span class='status-icon'>{icon}</span><div><strong>{esc(label)}</strong><small>{esc(detail)}</small></div></div>"


def pipeline_card_html(house_id: str) -> str:
    status = get_pipeline_status(house_id)
    analysis_done = bool(status.get("analysis_exists"))
    source_done = int(status.get("source_count") or 0) > 0
    media_done = int(status.get("downloaded_count") or 0) > 0 and int(status.get("pending_count") or 0) == 0
    exported = bool(status.get("exported_at"))
    failed = int(status.get("failed_count") or 0)
    state_error = str(status.get("state") or "") == "error"

    steps = [
        _pipeline_step("Inserat erfasst", source_done, not source_done, f"{status.get('source_count', 0)} Quelle(n) gespeichert"),
        _pipeline_step(
            "Medien geladen",
            media_done,
            source_done and not media_done,
            f"{status.get('downloaded_count', 0)} geladen · {status.get('pending_count', 0)} offen · {failed} Fehler",
            error=failed > 0 and not media_done,
        ),
        _pipeline_step(
            "Zur Analyse bereitgestellt",
            exported,
            media_done and not exported,
            format_datetime(status.get("exported_at"), "ZIP wird nach GitHub exportiert"),
            error=state_error and not exported,
        ),
        _pipeline_step(
            "ChatGPT-Analyse importiert",
            analysis_done,
            exported and not analysis_done,
            format_datetime(
                status.get("analysis_imported_at"),
                "Ergebnis wird automatisch übernommen" if exported else "wartet auf Export",
            ),
            error=state_error and exported and not analysis_done,
        ),
    ]
    error_html = f"<p class='danger'><strong>Letzter Fehler:</strong> {esc(status.get('last_error'))}</p>" if status.get("last_error") else ""
    return f"""
    <div class="card">
      <h2>Verarbeitungsstatus</h2>
      <p>{product_ui._pipeline_badge(status)}<span class="pill">aktualisiert: {esc(format_datetime(status.get('updated_at')))}</span></p>
      <div class="status-steps">{''.join(steps)}</div>
      {error_html}
      <form method="post" action="{esc(house_id)}/analysis/retry" data-loading="Analysepaket wird erneut bereitgestellt …">
        <button type="submit">Analyse erneut anstoßen</button>
      </form>
    </div>
    """


def _price_assessment_html(analysis: dict[str, Any]) -> str:
    price = analysis.get("price_assessment") or {}
    if not isinstance(price, dict) or not any(price.get(key) not in (None, "") for key in [
        "fair_value_low_eur", "fair_value_high_eur", "suggested_first_offer_eur",
        "suggested_target_price_eur", "maximum_recommended_price_eur"
    ]):
        return "<p class='muted'>Diese Analyse enthält noch keine Kaufpreisempfehlung. Über „Analyse erneut anstoßen“ wird das erweiterte Bewertungsformat verwendet.</p>"
    return f"""
    <div class="subtle-box">
      <h3>Kaufpreiseinschätzung</h3>
      <div class="grid">
        <div><strong>Angebotspreis</strong><br>{format_eur(price.get('asking_price_eur'))}</div>
        <div><strong>Grob fairer Bereich</strong><br>{_money_range(price.get('fair_value_low_eur'), price.get('fair_value_high_eur'))}</div>
        <div><strong>Erstes Angebot</strong><br>{format_eur(price.get('suggested_first_offer_eur'))}</div>
        <div><strong>Zielpreis</strong><br>{format_eur(price.get('suggested_target_price_eur'))}</div>
        <div><strong>Empfohlene Obergrenze</strong><br>{format_eur(price.get('maximum_recommended_price_eur'))}</div>
        <div><strong>Sicherheit</strong><br>{esc(price.get('confidence') or 'niedrig')}</div>
      </div>
      <p>{esc(price.get('reasoning') or '')}</p>
      <p class="muted">Grobe KI-Einschätzung aus Inseratsdaten, Bildern und Investitionsbedarf; kein Verkehrswertgutachten.</p>
    </div>
    """


def _investment_html(analysis: dict[str, Any]) -> str:
    estimate = analysis.get("estimated_investment_eur") or {}
    items = analysis.get("investment_items") or []
    total = analysis.get("estimated_total_cost_eur") or {}
    rows: list[str] = []
    if isinstance(items, list):
        for item in items[:12]:
            if not isinstance(item, dict):
                continue
            rows.append(
                f"<tr><td>{esc(item.get('category'))}</td><td>{esc(item.get('measure'))}</td><td>{esc(item.get('priority'))}</td><td>{_money_range(item.get('low_eur'), item.get('high_eur'))}</td><td>{esc(item.get('confidence'))}</td><td>{esc(item.get('basis'))}</td></tr>"
            )
    if not isinstance(estimate, dict):
        estimate = {}
    if not isinstance(total, dict):
        total = {}
    total_html = ""
    if total.get("low") not in (None, "") or total.get("high") not in (None, ""):
        acquisition_note = "inklusive Kaufnebenkosten" if total.get("includes_acquisition_costs") else "ohne Kaufnebenkosten und Finanzierung"
        total_html = f"<p><strong>Grobe Projektkosten:</strong> {_money_range(total.get('low'), total.get('high'))} <span class='muted'>({esc(acquisition_note)})</span></p><p>{esc(total.get('comment') or '')}</p>"
    return f"""
    <div class="subtle-box">
      <h3>Voraussichtliche Investitionen</h3>
      <p><strong>Gesamte Investitionsspanne:</strong> {_money_range(estimate.get('low'), estimate.get('high'))} · Sicherheit: {esc(estimate.get('confidence') or 'niedrig')}</p>
      <p>{esc(estimate.get('comment') or '')}</p>
      {f'<table><tr><th>Bereich</th><th>Maßnahme</th><th>Priorität</th><th>Kosten</th><th>Sicherheit</th><th>Grundlage</th></tr>{"".join(rows)}</table>' if rows else '<p class="muted">Keine einzelnen Investitionsposten angegeben.</p>'}
      {total_html}
    </div>
    """


def analysis_card_html(house_id: str) -> str:
    analysis = load_analysis(house_id)
    if not analysis:
        return """
        <div class="card">
          <h2>ChatGPT-Analyse</h2>
          <p class="muted">Noch kein Ergebnis vorhanden. Nach dem Import ersetzt der KI-Score die vorläufige Datenbewertung.</p>
        </div>
        """
    positives = analysis.get("positive_findings") or []
    risks = analysis.get("risk_findings") or []
    positive_html = "".join(f"<li>{esc(item)}</li>" for item in positives[:8]) or "<li class='muted'>Keine Chancen eingetragen.</li>"
    risk_html = "".join(f"<li>{esc(item)}</li>" for item in risks[:8]) or "<li class='muted'>Keine Risiken eingetragen.</li>"
    return f"""
    <div class="card">
      <h2>KI-Bewertung, Kaufpreis und Investitionen</h2>
      <p><span class="pill good">Gesamtbewertung {esc(analysis.get('new_score'))}/100</span><span class="pill">Sicherheit: {esc(analysis.get('confidence'))}</span><span class="pill">{esc(format_datetime(analysis.get('analysis_date')))}</span></p>
      <p>{esc(analysis.get('summary') or '')}</p>
      <p><strong>Empfehlung:</strong> {esc(analysis.get('recommendation') or '')}</p>
      {_price_assessment_html(analysis)}
      {_investment_html(analysis)}
      <div class="grid"><div><strong>Chancen</strong><ul>{positive_html}</ul></div><div><strong>Risiken</strong><ul>{risk_html}</ul></div></div>
    </div>
    """


def diagnostics_html(house_id: str) -> str:
    media = list_media(house_id)
    sources = list_sources(house_id)
    evidence = list_evidence(house_id)
    events = list_pipeline_events(house_id)
    source_rows = "".join(
        f"<tr><td>{esc(item.get('source_name'))}</td><td><a href='{esc(item.get('source_url'))}' target='_blank'>Direktlink</a></td><td>{esc(item.get('parser_status'))}</td></tr>"
        for item in sources
    )
    evidence_rows = "".join(
        f"<tr><td>{esc(item.get('field_name'))}</td><td>{esc(item.get('value_text'))}</td><td>{esc(item.get('confidence'))}</td><td>{esc(item.get('source_text_snippet'))}</td></tr>"
        for item in evidence[:40]
    )
    event_rows = "".join(
        f"<tr><td>{esc(format_datetime(item.get('created_at')))}</td><td>{esc(item.get('stage'))}</td><td>{esc(item.get('state'))}</td><td>{esc(item.get('message'))}</td></tr>"
        for item in events
    )
    failed_rows = "".join(
        f"<tr><td>{esc(item.get('kind'))}</td><td>{esc(item.get('original_url'))}</td><td class='danger'>{esc(item.get('download_error'))}</td></tr>"
        for item in media
        if item.get("download_status") == "failed"
    )
    return f"""
    <div class="card compact-card">
      <details class="tech-details">
        <summary><strong>Diagnose und technische Details</strong></summary>
        <div class="top-actions">
          <form method="post" action="{esc(house_id)}/download-media" data-loading="Medien werden heruntergeladen …"><button class="secondary" type="submit">Medien erneut laden</button></form>
          <form method="post" action="{esc(house_id)}/cleanup-media" data-loading="Medien werden bereinigt …"><button class="secondary" type="submit">Medien bereinigen</button></form>
        </div>
        <h3>Pipeline-Ereignisse</h3><table><tr><th>Zeit</th><th>Stufe</th><th>Status</th><th>Meldung</th></tr>{event_rows or '<tr><td colspan="4" class="muted">Noch keine Ereignisse.</td></tr>'}</table>
        <h3>Quellen</h3><table><tr><th>Quelle</th><th>Link</th><th>Status</th></tr>{source_rows}</table>
        <h3>Feldherkunft</h3><table><tr><th>Feld</th><th>Wert</th><th>Sicherheit</th><th>Snippet</th></tr>{evidence_rows}</table>
        {f'<h3>Medienfehler</h3><table><tr><th>Typ</th><th>URL</th><th>Fehler</th></tr>{failed_rows}</table>' if failed_rows else ''}
      </details>
    </div>
    """


def _append_time_script(module: Any) -> None:
    current = str(getattr(module, "PRODUCT_CSS", ""))
    if "__hauscheckLocalTimeInstalled" not in current:
        setattr(module, "PRODUCT_CSS", current + LOCAL_TIME_SCRIPT)


def register_valuation_ui(app: FastAPI) -> None:
    del app
    product_ui.pipeline_card_html = pipeline_card_html
    product_ui.analysis_card_html = analysis_card_html
    product_ui.diagnostics_html = diagnostics_html
    for module in [product_ui, search_automation_ui, dashboard_automation_ui]:
        _append_time_script(module)
