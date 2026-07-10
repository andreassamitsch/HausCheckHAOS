# HausCheck Pro Add-on

## Start

Nach der Installation das Add-on starten und über den Home-Assistant-Ingress öffnen.

## Aktueller Funktionsumfang v0.5.5

- Hausakten-Dashboard
- Direktlink-Import
- konservativer Willhaben-Parser
- SQLite-Datenbank unter `/share/hauscheck/hauscheck.db`
- lokale Medienablage unter `/share/hauscheck/projects/`
- Bild-URL-Erkennung und automatischer Bilddownload beim Import
- Medienfilter gegen Logos, Icons und Duplikate
- manuelle Medien-Uploads
- zentrale Suchprofile mit Kriterien
- automatisch erzeugte Willhaben-Suchquellen über eine oder mehrere PLZ/areaIds
- optionale manuelle Willhaben-Such-URL für Spezialfälle, z. B. Umkreis
- persistente Kandidatenliste mit Einzelimport
- Kandidaten-Vorprüfung anhand Preis, Wohnfläche, Grundstück und HWB
- Vorschaubild je Kandidat bevorzugt aus der Portal-/Willhaben-Übersicht
- Hauskarten nutzen bevorzugt das Portal-/Willhaben-Vorschaubild
- mobilfreundliche Kandidaten-Karten statt breiter Tabelle
- regelbasierte Erstbewertung / Score je Kandidat und Hausakte
- manueller ChatGPT-Analyseworkflow per ZIP Export/JSON Import
- Hausakte manuell bearbeiten
- Hausakte vollständig löschen inklusive geladener Dateien
- Galerie/Slider oben in der Hausakte; Klick öffnet Bilder groß
- Exposé-PDF hochladen und Textdaten auslesen
- optionale API-/MCP-Bridge bleibt vorhanden, kann aber ignoriert werden

## Hausakte bearbeiten und löschen

In der Hausakte gibt es jetzt aufklappbare Bereiche:

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
Adresse / Lage
Preis
Wohnfläche
Grundstück
Zimmer
Baujahr
HWB
fGEE
Heizung
```

Zusätzlich versucht HausCheck, Bilder aus dem PDF zu extrahieren und der Hausakte hinzuzufügen. Je nach PDF-Aufbau kann das vollständig, teilweise oder gar nicht funktionieren.

## Empfohlener Analyseworkflow ohne API-Kosten

1. Hausakte öffnen.
2. Im Bereich **ChatGPT-Analyse** auf **Analysepaket exportieren** klicken.
3. Die ZIP-Datei in ChatGPT hochladen.
4. ChatGPT soll anhand der enthaltenen `README_PROMPT.md` eine Datei `hauscheck_analysis.json` erzeugen.
5. Diese JSON-Datei in HausCheck bei **KI-Analyse importieren** hochladen.
6. HausCheck zeigt KI-Score, Analysedatum, Zusammenfassung, Chancen, Risiken und Adress-/Lagehinweise in der Hausakte an.

Der Workflow benötigt:

```text
kein OpenAI API-Key
kein MCP
keine Nabu-Casa-Verbindung
keinen offenen Home-Assistant-Zugriff
```

## Inhalt des Analysepakets

Das ZIP enthält:

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

Die Bilder werden beim Export verkleinert, damit das Paket uploadfreundlich bleibt. Standard:

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

Die zentrale Logik lautet:

```text
Profil-Kriterien = Wahrheit
Portalquelle = automatisch erzeugt oder optional manuell
HausCheck-Filter = finale Kontrolle
HausCheck-Score = schnelle Priorisierung
Manueller ChatGPT-Export = ausführliche Bild-/Inseratanalyse ohne API-Kosten
```

## Optionale API-/MCP-Bridge

Die frühere API-/MCP-Bridge bleibt im Code vorhanden, ist aber für den empfohlenen manuellen Workflow nicht nötig.

Solange in den Add-on-Optionen kein `api_token` gesetzt ist, bleibt diese Bridge deaktiviert.

## Vorschaubilder

HausCheck versucht das Vorschaubild direkt aus der Portal-/Willhaben-Übersicht zu übernehmen. Das entspricht eher dem Bild, das auch auf der Suchergebnisseite sichtbar ist.

Wenn dort kein Bild erkannt wird, bleibt die Detailseite als Fallback. Nach dem Import wird das Portal-Vorschaubild an die Hausakte übergeben und in der Hauskarte bevorzugt angezeigt.

## Regelbasierte Erstbewertung

Der Score bewertet aktuell nur vorhandene Daten aus dem Inserat:

- Preis
- Wohnfläche
- Grundstück
- HWB
- Kandidatenstatus: neu / prüfen / gefiltert / importiert

Ergebnis:

```text
82-100  sehr interessant
68-81   interessant
50-67   prüfen
0-49    kritisch
```

Zusätzlich wird eine Bewertungssicherheit angezeigt:

```text
hoch    mehrere wichtige Werte vorhanden
mittel  einige Werte vorhanden
niedrig zu viele Werte fehlen
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

Die frühere Maske „Regionen / Orte“ wurde entfernt. Für Willhaben steuert jetzt **PLZ / areaId** die Suche. Die lokale Textprüfung über Orte war zu unzuverlässig und wird später sauber über Portaladapter/Geo-Daten ersetzt.

Die Umkreissuche mit `lat`, `lon` und `sfId` ist noch nicht automatisiert. Dafür kann vorerst weiterhin eine manuelle Willhaben-URL als Vorlage eingetragen werden.

## Ladeanzeige

Bei länger laufenden Aktionen zeigt HausCheck einen Ladehinweis mit Spinner:

- Suchprofil starten
- Inserat importieren und Bilder laden
- Datei hochladen
- ChatGPT-Analyse importieren
- Exposé PDF auslesen
- Hausakte löschen

## Kandidatenstatus

- `neu`: Kriterien aktuell erfüllt
- `prüfen`: nicht ausgeschlossen, aber mit Warnung
- `gefiltert`: harte Kriterien nicht erfüllt
- `importiert`: bereits als Hausakte vorhanden

## Import und Medien

Beim Import aus der Kandidatenliste oder per Direktlink werden Bilder und PDFs automatisch geladen.

Wichtig:

- Suchseiten werden nicht als Hausakten gespeichert.
- Nur echte Inserat-Direktlinks werden als Kandidaten angezeigt.
- Kandidaten bleiben gespeichert und werden beim Import als importiert markiert.
- Wenn keine Kandidaten erscheinen, wurde die Seite vermutlich dynamisch geladen oder durch Willhaben blockiert.

## Hinweise

Dies ist eine frühe MVP-Version. Die Parser sind bewusst konservativ:

- fehlende Werte bleiben leer
- Grundstück wird nur aus expliziten Grundstücksfeldern übernommen
- ohne genaue Adresse erfolgt keine belastbare Lageprüfung
- aktuell keine Captcha-/Login-Umgehung
- PDF-Bildextraktion hängt stark vom PDF-Aufbau ab

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
