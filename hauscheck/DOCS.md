# HausCheck Pro Add-on

## Start

Nach der Installation das Add-on starten und über den Home-Assistant-Ingress öffnen.

## Aktueller Funktionsumfang v0.5.8

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
- manueller ChatGPT-Analyseworkflow per ZIP Export/JSON Import
- GitHub AI Exchange für ZIP-Export und JSON-Rückimport
- Hausakte manuell bearbeiten und vollständig löschen
- Galerie/Slider oben in der Hausakte; unten alle Bilder einzeln
- Exposé-PDF hochladen und Textdaten auslesen
- optionale API-/MCP-Bridge bleibt vorhanden, kann aber ignoriert werden

## GitHub AI Exchange

Der GitHub AI Exchange ist der halbautomatische Austausch mit ChatGPT:

```text
HausCheck
→ Analysepaket nach GitHub exportieren
→ ChatGPT Task analysiert ZIP
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
github_repo: "andreassamitsch/HausCheckHAOS"
github_branch: "main"
github_token: "DEIN_GITHUB_TOKEN"
github_export_path: "ai_exchange/exports/pending"
github_result_path: "ai_exchange/results/pending"
github_done_path: "ai_exchange/results/done"
github_cleanup_after_import: true
```

Der Token braucht Schreibrechte auf das verwendete Repository. Am sichersten ist ein eigener Fine-Grained Token nur für dieses Repo mit Inhaltszugriff Lesen/Schreiben.

### Ablauf in der Hausakte

In jeder Hausakte gibt es den Bereich **GitHub AI Exchange**.

1. **Analysepaket nach GitHub exportieren** klicken.
2. HausCheck schreibt `<house_id>.zip` nach `ai_exchange/exports/pending/`.
3. Der stündliche ChatGPT Task prüft diesen Ordner.
4. ChatGPT schreibt das Ergebnis nach `ai_exchange/results/pending/<house_id>/hauscheck_analysis.json`.
5. In HausCheck **GitHub-Ergebnisse importieren** klicken.
6. HausCheck speichert die Analyse in der Hausakte.
7. Bei aktivem Cleanup werden pending-JSON und Export-ZIP aus GitHub entfernt; das JSON wird nach `results/done` archiviert.

## Hausakte bearbeiten und löschen

In der Hausakte gibt es aufklappbare Bereiche:

```text
Hausakte bearbeiten
Exposé PDF
Hausakte löschen
```

Bearbeitbar sind:

```text
Titel
Adresse / Lage
Adressstatus
Preis
Wohnfläche
Grundstück
Zimmer
Baujahr
HWB
fGEE
Heizung
Portal-Vorschaubild URL
Notizen
```

Beim Löschen werden entfernt:

```text
Hausakte
Quellen
Feldherkunft
Medien-Datenbankeinträge
KI-Analysen
Projektordner unter /share/hauscheck/projects/<house_id>
```

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

Zusätzlich versucht HausCheck, Bilder aus dem PDF zu extrahieren und der Hausakte hinzuzufügen. Je nach PDF-Aufbau kann das vollständig, teilweise oder gar nicht funktionieren.

## Manueller Analyseworkflow ohne GitHub

1. Hausakte öffnen.
2. Im Bereich **ChatGPT-Analyse** auf **Analysepaket exportieren** klicken.
3. ZIP in ChatGPT hochladen.
4. ChatGPT soll anhand der enthaltenen `README_PROMPT.md` eine Datei `hauscheck_analysis.json` erzeugen.
5. JSON-Datei in HausCheck bei **KI-Analyse importieren** hochladen.

Der Workflow benötigt:

```text
kein OpenAI API-Key
kein MCP
keine Nabu-Casa-Verbindung
keinen offenen Home-Assistant-Zugriff
```

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
  "address_hints": [
    {
      "hint": "möglicher Ortsteil / Lagehinweis",
      "basis": "z. B. Text, Aussicht, Straßenhinweis, Bildmerkmal",
      "confidence": "niedrig"
    }
  ],
  "image_findings": [],
  "recommendation": "Besichtigung sinnvoll, Unterlagen prüfen.",
  "next_steps": [],
  "score_reasoning": "Begründung des neuen Scores.",
  "limitations": []
}
```

HausCheck prüft, ob die `house_id` zur geöffneten Hausakte passt. Bestehende Analysen werden vor dem Überschreiben gesichert.

## Zentrale Suchprofile verwenden

1. In HausCheck auf **Suchprofile** klicken.
2. Name, zentrale Kriterien und Willhaben-PLZ/areaIds speichern.
3. Die Willhaben-URL kann leer bleiben.
4. Profil öffnen und **Suchprofil jetzt starten** klicken.
5. Kandidaten anhand Vorschaubild, Fakten und Score prüfen.
6. Kandidaten einzeln importieren. Bilder werden beim Import automatisch geladen.

Die Kandidatenansicht ist für Mobilgeräte optimiert: Bild, Titel, Fakten, Status, Score und Import-Schaltfläche stehen in einer Immobilien-Karte.

## Optionale API-/MCP-Bridge

Die frühere API-/MCP-Bridge bleibt im Code vorhanden, ist aber für den empfohlenen Workflow nicht nötig. Solange in den Add-on-Optionen kein `api_token` gesetzt ist, bleibt diese Bridge deaktiviert.

## Regelbasierte Erstbewertung

Der Score bewertet aktuell nur vorhandene Daten aus dem Inserat:

```text
Preis
Wohnfläche
Grundstück
HWB
Kandidatenstatus
```

Ergebnis:

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

Die Umkreissuche mit `lat`, `lon` und `sfId` ist noch nicht automatisiert. Dafür kann weiterhin eine manuelle Willhaben-URL als Vorlage eingetragen werden.

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
