# HausCheck Pro Add-on

## Aktueller Funktionsumfang v0.5.12

- Direktlink-Import und Suchprofil-Import von Immobilieninseraten
- automatischer Medien-Download
- Hausakten-Dashboard mit Galerie, Score und Bearbeitung
- ChatGPT-Analysepaket mit Bildern und strukturierter Rückgabe
- Gmail AI Exchange als bevorzugter Austauschweg
- GitHub AI Exchange bleibt als Fallback erhalten
- automatischer Import fertiger KI-Analysen

## Empfohlener Workflow: Gmail AI Exchange

```text
HausCheck
→ Inserat importieren
→ Bilder/PDFs laden
→ ZIP automatisch per Gmail senden

ChatGPT Task
→ liest stündlich Gmail-Mails mit Betreff HAUSCHECK_EXPORT <house_id>
→ analysiert ZIP anhand README_PROMPT.md
→ sendet Mail mit Betreff HAUSCHECK_RESULT <house_id>
→ JSON steht direkt im Mailbody

HausCheck
→ prüft alle 5 Minuten Gmail per IMAP
→ importiert fertige JSON-Analyse automatisch
```

## Gmail Add-on-Optionen

```yaml
gmail_exchange_enabled: true
gmail_auto_send_on_import: true
gmail_auto_import_results: true
gmail_import_interval_minutes: 5
gmail_smtp_host: "smtp.gmail.com"
gmail_smtp_port: 587
gmail_imap_host: "imap.gmail.com"
gmail_imap_port: 993
gmail_username: "deineadresse@gmail.com"
gmail_app_password: "DEIN_GOOGLE_APP_PASSWORT"
gmail_to: "deineadresse@gmail.com"
gmail_from_name: "HausCheck Pro"
gmail_mark_results_seen: true
```

Hinweise:

- `gmail_username` ist deine Gmail-Adresse.
- `gmail_to` kann dieselbe Adresse sein.
- `gmail_app_password` ist nicht dein normales Google-Passwort, sondern ein Google-App-Passwort.
- Export-Mails haben den Betreff `HAUSCHECK_EXPORT <house_id>`.
- Ergebnis-Mails müssen den Betreff `HAUSCHECK_RESULT <house_id>` haben.
- HausCheck akzeptiert `hauscheck_analysis.json` als Anhang oder reinen JSON-Text im Mailbody.

## GitHub AI Exchange Fallback

```yaml
github_exchange_enabled: true
github_auto_export_on_import: true
github_auto_import_results: true
github_auto_import_interval_minutes: 5
github_repo: "andreassamitsch/HausCheckAIExchange"
github_branch: "main"
github_token: "DEIN_GITHUB_TOKEN"
github_export_path: "ai_exchange/exports/pending"
github_result_path: "ai_exchange/results/pending"
github_done_path: "ai_exchange/results/done"
github_cleanup_after_import: true
```

GitHub bleibt verfügbar, falls Gmail deaktiviert wird oder größere ZIPs anders transportiert werden sollen.

## Inhalt des Analysepakets

```text
hauscheck_export_<house_id>_<titel>.zip
├── README_PROMPT.md
├── listing.json
├── evidence.json
├── current_score.json
├── import_schema.json
├── image_manifest.json
├── images/
│   ├── 01.jpg
│   ├── 02.jpg
│   └── ...
└── original/
    └── source_urls.txt
```

Standard:

```text
max. 12 Bilder
max. 1600 px Kantenlänge
JPEG Qualität 84
```

## Erwartete Rückgabe von ChatGPT

Betreff:

```text
HAUSCHECK_RESULT <house_id>
```

Mailbody als reines JSON, ohne Markdown:

```json
{
  "house_id": "abc12345",
  "analysis_date": "2026-07-10T12:00:00+00:00",
  "new_score": 78,
  "confidence": "mittel",
  "summary": "Kurze Zusammenfassung.",
  "positive_findings": [],
  "risk_findings": [],
  "estimated_investment_eur": {
    "low": 15000,
    "high": 45000,
    "confidence": "niedrig",
    "comment": "Nur grobe Bild-/Inseratsschätzung."
  },
  "address_hints": [],
  "image_findings": [],
  "recommendation": "Besichtigung sinnvoll, Unterlagen prüfen.",
  "next_steps": [],
  "score_reasoning": "Begründung des neuen Scores.",
  "limitations": []
}
```

HausCheck prüft, ob die `house_id` zur lokalen Hausakte passt. Bestehende Analysen werden vor dem Überschreiben gesichert.

## Exposé PDF

PDFs können direkt in der Hausakte hochgeladen werden. HausCheck versucht daraus Preis, Wohnfläche, Grundstück, Zimmer, Baujahr, HWB, fGEE und Heizung zu erkennen.

Adressen aus PDFs werden **nicht automatisch** übernommen, weil PDFs oft Makler- oder Büroanschriften enthalten. Mögliche Adressen werden nur als `pdf_address_hint` in der Feldherkunft gespeichert.

## Zentrale Suchprofile

1. In HausCheck auf **Suchprofile** klicken.
2. Name, zentrale Kriterien und Willhaben-PLZ/areaIds speichern.
3. Die Willhaben-URL kann leer bleiben.
4. Profil öffnen und **Suchprofil jetzt starten** klicken.
5. Kandidaten prüfen und einzeln importieren.
6. Nach dem Import startet Gmail/GitHub Exchange automatisch, wenn konfiguriert.

## Datenablage

```text
/share/hauscheck/
├── hauscheck.db
├── projects/
│   └── <house_id>/
│       ├── images/
│       ├── pdfs/
│       ├── exports/
│       └── analysis/
│           └── hauscheck_analysis.json
└── logs/
```

## Hinweise

Dies ist eine frühe MVP-Version. Die Parser sind bewusst konservativ:

- fehlende Werte bleiben leer
- Grundstück wird nur aus expliziten Grundstücksfeldern übernommen
- ohne genaue Adresse erfolgt keine belastbare Lageprüfung
- aktuell keine Captcha-/Login-Umgehung
- PDF-Bildextraktion hängt stark vom PDF-Aufbau ab
