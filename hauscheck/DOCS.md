# HausCheck Pro Add-on

## Aktueller Funktionsumfang v0.7.1

- Direktlink-Import von Immobilieninseraten
- zeitgesteuerte Willhaben-Suchprofile
- automatische Kandidatenprüfung anhand der hinterlegten Muss- und Wunschkriterien
- optionaler automatischer Vollimport geeigneter Kandidaten
- automatischer Medien-Download
- automatische Erstellung und Übertragung des Analysepakets nach GitHub
- ChatGPT-Bildanalyse über GitHub-Actions-Artefakte
- automatischer Rückimport fertiger Analysen
- KI-Gesamtbewertung mit Kaufpreis- und Investitionsempfehlung
- Hausakten-Dashboard mit Galerie, Score, Pipeline-Status und Diagnosebereich
- lokale Zeitanzeige im Format `TT.MM.JJJJ HH:MM`

## Produktiver Ablauf

```text
Willhaben-Suchprofil
→ Suchlauf nach konfiguriertem Intervall
→ Kandidaten speichern und gegen Filter prüfen
→ bei Vollautomatik: Kandidat ab Mindestscore importieren
→ Hausakte anlegen
→ Bilder und PDFs laden
→ Analyse-ZIP nach GitHub pending exportieren
→ GitHub Action erzeugt ein binäres Artifact
→ ChatGPT lädt und analysiert ZIP und Bilder
→ hauscheck_analysis.json nach results/pending schreiben
→ HausCheck importiert das Ergebnis automatisch
```

## Bewertungssystem

Vor der KI-Analyse verwendet HausCheck eine regelbasierte Daten-Vorprüfung aus Preis, Wohnfläche, Grundstück, HWB und Kandidatenstatus.

Nach dem Import einer ChatGPT-Analyse wird `new_score` zur maßgeblichen Gesamtbewertung. Die frühere Regelbewertung bleibt in der Hausakte nur noch als einklappbare **Daten-Vorprüfung** sichtbar.

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

Die Kaufpreiseinschätzung ist kein Verkehrswertgutachten. Ohne belastbare Vergleichsobjekte wird sie mit niedriger oder mittlerer Sicherheit ausgewiesen.

Bereits vorhandene Analysen im alten Format bleiben lesbar. Über **Analyse erneut anstoßen** wird das erweiterte Format mit Kaufpreis- und Investitionsfeldern erzeugt.

## Zeitzone

```yaml
display_timezone: "Europe/Vienna"
```

Alle sichtbaren Zeitpunkte werden auf diese Zeitzone umgerechnet und als `TT.MM.JJJJ HH:MM` angezeigt.

## Suchmodi

### Nur manuell

Das Suchprofil läuft nur über **Jetzt ausführen**. Kandidaten werden nicht automatisch importiert.

### Automatisch suchen, manuell importieren

HausCheck führt das Profil zeitgesteuert aus und aktualisiert die Kandidatenliste. Eine Hausakte wird erst über **Hausakte anlegen & analysieren** erstellt.

### Automatisch suchen und importieren

HausCheck importiert ausschließlich Kandidaten, die:

- den Status `new` erhalten haben,
- noch nicht als Hausakte vorhanden sind,
- mindestens den konfigurierten Auto-Import-Score erreichen.

Die Anzahl automatischer Importe pro Lauf ist begrenzt.

## Globale Suchoptionen

```yaml
search_automation_enabled: true
search_scheduler_poll_seconds: 60
```

`search_scheduler_poll_seconds` ist nur das interne Prüfintervall. Der tatsächliche Suchabstand wird pro Suchprofil eingestellt und beträgt mindestens 15 Minuten.

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

Für die erste Testphase ist der Modus **automatisch suchen, manuell importieren** sinnvoll. Nach Kontrolle der Treffer kann auf Vollautomatik umgestellt werden.

## Kandidaten-Datenbank

Je Treffer werden unter anderem gespeichert:

```text
Provider
externe Inserat-ID
Quell-URL
kanonische URL
Titel
Preis
Wohnfläche
Grundstück
HWB
Vorschaubild
Filterentscheidung
Filterbegründungen
Erstfund
letzte Sichtung
Inhalts-Hash
Änderungszeitpunkt
Änderungszähler
Importentscheidung
zugehörige Hausakte
```

Doppelimporte werden über Quell-URL und Willhaben-Inserat-ID verhindert.

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

Der GitHub-Token muss Schreibrechte auf das Exchange-Repository haben.

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

Standardmäßig werden höchstens zwölf Bilder mit maximal 1.600 Pixel Kantenlänge exportiert.

## Pipeline-Status

Jede Hausakte zeigt:

```text
Inserat erfasst
Medien geladen
Zur Analyse bereitgestellt
ChatGPT-Analyse importiert
```

Fehler und technische Ereignisse befinden sich unter **Diagnose und technische Details**. Mit **Analyse erneut anstoßen** kann ein Export wiederholt werden.

## Exposé PDF

PDFs können direkt in der Hausakte hochgeladen werden. HausCheck versucht daraus Preis, Wohnfläche, Grundstück, Zimmer, Baujahr, HWB, fGEE und Heizung zu erkennen.

Adressen aus PDFs werden nicht automatisch übernommen, weil PDFs häufig Makler- oder Büroanschriften enthalten. Mögliche Adressen werden nur als Hinweis in der Feldherkunft gespeichert.

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
- Grundstücksflächen werden nur aus expliziten Inseratsfeldern übernommen.
- Ohne genaue Adresse erfolgt keine belastbare Lageprüfung.
- Captchas oder Login-Sperren werden nicht umgangen.
- Werbe- und KI-generierte Inseratbilder werden bei der ChatGPT-Analyse nicht als Zustandsnachweis verwendet.
- Kaufnebenkosten, Finanzierung und Steuern werden in der Projektkostenspanne nur berücksichtigt, wenn dies ausdrücklich dokumentiert ist.
