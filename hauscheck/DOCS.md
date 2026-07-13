# HausCheck Pro Add-on

## Aktueller Funktionsumfang v0.8.0

- fokussierte Startseite mit aktiven Hausakten
- Willhaben-Suche direkt über die Lupe
- Suchprofile unter **Einstellungen → Suchprofile**
- zeitgesteuerte oder vollautomatische Willhaben-Suche
- automatische Kandidatenprüfung und optionaler Vollimport
- automatischer Medien-Download und GitHub-Analyseworkflow
- KI-Gesamtbewertung mit Kaufpreis- und Investitionsempfehlung
- Ablehnungsarchiv für Hausakten und Kandidaten
- lokale Zeitanzeige im Format `TT.MM.JJJJ HH:MM`

## Bedienung der Startseite

Die Startseite zeigt nur aktive Hausakten. Oben stehen vier kompakte Aktionen:

```text
＋   Inserat direkt hinzufügen
🔍  alle aktiven Suchprofile sofort ausführen
🗑️  abgelehnte Hausakten und Kandidaten öffnen
⚙️  Einstellungen öffnen
```

Jede Hausakte kann direkt über das Mülleimer-Symbol abgelehnt werden. Dabei wird sie nicht sofort gelöscht, sondern aus der Hauptübersicht ausgeblendet und in das Ablehnungsarchiv verschoben.

Im Ablehnungsarchiv kann ein Objekt:

- wiederhergestellt oder
- endgültig inklusive Projektdateien gelöscht werden.

Abgelehnte Kandidaten bleiben auch bei späteren Suchläufen abgelehnt.

## HWB- und Dezimalwerte

Für HWB und fGEE gelten Punkt und Komma als Dezimaltrennzeichen:

```text
306.1  → 306,1
306,1  → 306,1
```

HausCheck priorisiert Energiekennzahlen aus strukturierten Tabellen, Definitionslisten und Wertelisten. Erst wenn dort kein Wert gefunden wird, wird der allgemeine Seitentext verwendet. Dadurch überschreibt eine unklare Nebenfundstelle keinen eindeutig angegebenen Listenwert mehr.

## Produktiver Ablauf

```text
Willhaben-Suche
→ Kandidat speichern und filtern
→ optional Hausakte automatisch anlegen
→ Bilder und PDFs laden
→ Analyse-ZIP nach GitHub exportieren
→ GitHub Action erzeugt ein binäres Artifact
→ ChatGPT analysiert Inseratsdaten und Bilder
→ Ergebnis nach GitHub zurückschreiben
→ HausCheck importiert die Analyse automatisch
```

## Bewertungssystem

Vor der KI-Analyse verwendet HausCheck eine regelbasierte Daten-Vorprüfung aus Preis, Wohnfläche, Grundstück, HWB und Kandidatenstatus.

Nach dem Import einer ChatGPT-Analyse wird `new_score` zur maßgeblichen Gesamtbewertung. Die frühere Regelbewertung bleibt nur noch als einklappbare Daten-Vorprüfung sichtbar.

Die KI-Auswertung kann zusätzlich enthalten:

```text
fairer Kaufpreisbereich
erstes Verhandlungsangebot
realistischer Zielpreis
empfohlene Preisobergrenze
Gesamtsumme möglicher Investitionen
einzelne Investitionsposten mit Priorität und Kostenspanne
grobe Projektkosten aus Zielkaufpreis plus Investitionen
```

Die Kaufpreiseinschätzung ist kein Verkehrswertgutachten. Fehlende oder nicht sichtbare Bauteile werden nicht als gesichert behandelt.

## Suchmodi

### Nur manuell

Das Suchprofil läuft nur über die Lupe beziehungsweise **Jetzt ausführen**.

### Automatisch suchen, manuell importieren

HausCheck aktualisiert die Kandidatenliste zeitgesteuert. Eine Hausakte wird erst nach Bestätigung angelegt.

### Automatisch suchen und importieren

HausCheck importiert nur Kandidaten, die:

- den Status `new` haben,
- noch nicht als Hausakte vorhanden sind,
- mindestens den konfigurierten Auto-Import-Score erreichen.

Die Anzahl automatischer Importe je Suchlauf ist begrenzt.

## Empfohlenes Suchprofil

```text
Regionen:
Wies, Eibiswald, Oberhaag, Gleinstätten,
Bad Schwanberg, Pölfing-Brunn, Frauental, Deutschlandsberg

Zielpreis:             380.000 €
Harte Preisgrenze:     400.000 €
Mindestwohnfläche:     120 m²
Wunsch-Grundstück:     700 m²
HWB Warnung:           200
HWB kritisch:          300
Prüfbegriffe:          B76, B69, Bundesstraße, Hauptstraße
Intervall:             60 Minuten
Auto-Import-Score:     68
Max. Auto-Importe:     2 je Lauf
```

## Globale Optionen

```yaml
display_timezone: "Europe/Vienna"
search_automation_enabled: true
search_scheduler_poll_seconds: 60
```

`search_scheduler_poll_seconds` ist nur das interne Prüfintervall. Der tatsächliche Suchabstand wird pro Suchprofil eingestellt und beträgt mindestens 15 Minuten.

## GitHub AI Exchange

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
│   └── ...
└── original/
    └── source_urls.txt
```

## Pipeline-Status

Jede Hausakte zeigt:

```text
Inserat erfasst
Medien geladen
Zur Analyse bereitgestellt
ChatGPT-Analyse importiert
```

Fehler und technische Ereignisse befinden sich unter **Diagnose und technische Details**.

## Datenablage

```text
/share/hauscheck/
├── hauscheck.db
└── projects/
    └── <house_id>/
        ├── html/
        ├── images/
        ├── pdfs/
        ├── exports/
        └── analysis/
            └── hauscheck_analysis.json
```

## Hinweise

- Fehlende Werte bleiben leer und werden nicht erfunden.
- Ohne genaue Adresse erfolgt keine belastbare Lageprüfung.
- Captchas oder Login-Sperren werden nicht umgangen.
- Werbe- und KI-generierte Inseratbilder werden nicht als Zustandsnachweis verwendet.
- Kaufnebenkosten, Finanzierung und Steuern werden nur eingerechnet, wenn dies ausdrücklich dokumentiert ist.
