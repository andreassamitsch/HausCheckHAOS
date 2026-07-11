# HausCheck Pro Add-on

## Start

Nach der Installation das Add-on starten und über den Home-Assistant-Ingress öffnen.

## Aktueller Funktionsumfang v0.5.10

- Hausakten-Dashboard
- Direktlink-Import
- konservativer Willhaben-Parser
- SQLite-Datenbank unter `/share/hauscheck/hauscheck.db`
- lokale Medienablage unter `/share/hauscheck/projects/`
- Bild-URL-Erkennung und automatischer Bilddownload beim Import
- zentrale Suchprofile mit Kriterien und Willhaben-PLZ/areaIds
- Kandidatenkarten mit Portal-/Willhaben-Vorschaubild
- Hauskarten nutzen bevorzugt das Portal-/Willhaben-Vorschaubild
- regelbasierte Erstbewertung / Score je Kandidat und Hausakte
- GitHub AI Exchange für ZIP-Export und JSON-Rückimport
- automatischer GitHub-AI-Export direkt nach Inserat-Import
- manueller ChatGPT-Analyseworkflow per ZIP Export/JSON Import bleibt verfügbar
- Hausakte manuell bearbeiten und vollständig löschen
- Galerie/Slider oben in der Hausakte; unten alle Bilder einzeln
- Exposé-PDF hochladen und Textdaten auslesen

## GitHub AI Exchange

Der GitHub AI Exchange ist der halbautomatische Austausch mit ChatGPT:

```text
HausCheck
→ Inserat importieren
→ Bilder/PDFs laden
→ Analysepaket automatisch nach GitHub exportieren
→ ChatGPT Task analysiert ZIP stündlich
→ ChatGPT schreibt hauscheck_analysis.json nach GitHub
→ HausCheck importiert GitHub-Ergebnisse
```

Standardpfade:

```text
ai_exchange/
├── exports/
│   └── pending/
│       └── <house_id>.zip
├── results/
│   └── pending/
│       └── <house_id>/hauscheck_analysis.json
└── results/
    └── done/
        └── <house_id>/hauscheck_analysis_<datum>.json
```

### Add-on-Optionen

```yaml
github_exchange_enabled: true
github_auto_export_on_import: true
github_repo: "andreassamitsch/HausCheckAIExchange"
github_branch: "main"
github_token: "DEIN_GITHUB_TOKEN"
github_export_path: "ai_exchange/exports/pending"
github_result_path: "ai_exchange/results/pending"
github_done_path: "ai_exchange/results/done"
github_cleanup_after_import: true
```

Der Token braucht Schreibrechte auf das Austausch-Repository. Am sichersten ist ein eigener Fine-Grained Token nur für `HausCheckAIExchange` mit Inhaltszugriff Lesen/Schreiben.

### Ablauf automatisch

1. Inserat aus Suchprofil oder Direktlink importieren.
2. HausCheck erstellt die Hausakte und lädt Medien.
3. Wenn `github_auto_export_on_import` aktiv ist, wird automatisch `<house_id>.zip` nach `ai_exchange/exports/pending/` geschrieben.
4. Der stündliche ChatGPT Task prüft diesen Ordner.
5. ChatGPT schreibt das Ergebnis nach `ai_exchange/results/pending/<house_id>/hauscheck_analysis.json`.
6. In HausCheck **GitHub-Ergebnisse importieren** klicken.
7. Bei aktivem Cleanup werden pending-JSON und Export-ZIP aus GitHub entfernt; das JSON wird nach `results/done` archiviert.

Fehler beim automatischen GitHub-Export blockieren den Hausimport nicht. Details stehen im Add-on-Log.

### Ablauf manuell

In jeder Hausakte gibt es den Bereich **GitHub AI Exchange**.

- **Analysepaket nach GitHub exportieren** erzeugt/überschreibt das ZIP im Austausch-Repo.
- **GitHub-Ergebnisse importieren** liest alle fertigen `hauscheck_analysis.json` aus `results/pending` ein.

## Hausakte bearbeiten und löschen

Bearbeitbar sind Titel, Adresse/Lage, Adressstatus, Preis, Wohnfläche, Grundstück, Zimmer, Baujahr, HWB, fGEE, Heizung, Portal-Vorschaubild-URL und Notizen.

Beim Löschen werden Hausakte, Quellen, Feldherkunft, Medien-Datenbankeinträge, KI-Analysen und der Projektordner unter `/share/hauscheck/projects/<house_id>` entfernt.

## Exposé PDF

PDFs können direkt in der Hausakte hochgeladen werden.

HausCheck versucht daraus zu erkennen und zu aktualisieren:

```text
Preis
Wohnfläche
Grundstück
Zimmer
Baujahr
HWB
fGEE
Heizung
```

Adressen aus PDFs werden **nicht automatisch** übernommen, weil PDFs oft Makler- oder Büroanschriften enthalten. Mögliche Adressen werden nur als `pdf_address_hint` in der Feldherkunft gespeichert.

## Manueller Analyseworkflow ohne GitHub

1. Hausakte öffnen.
2. Im Bereich **ChatGPT-Analyse** auf **Analysepaket exportieren** klicken.
3. ZIP in ChatGPT hochladen.
4. ChatGPT soll anhand der enthaltenen `README_PROMPT.md` eine Datei `hauscheck_analysis.json` erzeugen.
5. JSON-Datei in HausCheck bei **KI-Analyse importieren** hochladen.

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

## Erwartete Rückgabedatei von ChatGPT

Name exakt:

```text
hauscheck_analysis.json
```

Mindeststruktur:

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

HausCheck prüft, ob die `house_id` zur Hausakte passt. Bestehende Analysen werden vor dem Überschreiben gesichert.

## Zentrale Suchprofile verwenden

1. In HausCheck auf **Suchprofile** klicken.
2. Name, zentrale Kriterien und Willhaben-PLZ/areaIds speichern.
3. Die Willhaben-URL kann leer bleiben.
4. Profil öffnen und **Suchprofil jetzt starten** klicken.
5. Kandidaten anhand Vorschaubild, Fakten und Score prüfen.
6. Kandidaten einzeln importieren. Bilder werden beim Import automatisch geladen und danach wird das Analysepaket automatisch nach GitHub exportiert.

## Optionale API-/MCP-Bridge

Die frühere API-/MCP-Bridge bleibt im Code vorhanden, ist aber für den empfohlenen Workflow nicht nötig. Solange in den Add-on-Optionen kein `api_token` gesetzt ist, bleibt diese Bridge deaktiviert.

## Regelbasierte Erstbewertung

Der Score bewertet aktuell nur vorhandene Daten aus dem Inserat: Preis, Wohnfläche, Grundstück, HWB und Kandidatenstatus.

```text
82-100  sehr interessant
68-81   interessant
50-67   prüfen
0-49    kritisch
```

Wichtig: Der Score ist noch keine Marktwertschätzung. Fehlende Werte werden nicht erfunden.

## Automatische Willhaben-Quelle

Wenn keine Willhaben-URL eingetragen wird, erzeugt HausCheck pro PLZ/areaId eine Willhaben-Suche nach diesem Muster:

```text
https://www.willhaben.at/iad/immobilien/haus-kaufen/haus-angebote
?areaId=<PLZ oder areaId>
&page=1
&PRICE_TO=<harte Preisgrenze>
&ESTATE_SIZE/LIVING_AREA_FROM=<Mindestwohnfläche>
```

Beispiel Wies:

```text
areaId=8551
```

Mehrere PLZ/areaIds können kommagetrennt eingetragen werden:

```text
8551,8552,8544,8553
```

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
