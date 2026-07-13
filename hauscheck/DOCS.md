# HausCheck Pro Add-on

## Aktueller Funktionsumfang v0.9.0

- fokussierte Startseite mit aktiven Hausakten
- Willhaben-Suche direkt über die Lupe
- Suchprofile unter **Einstellungen → Suchprofile**
- neues Suchprofil oben über den Plus-Button
- Suchprofile inklusive Kandidaten- und Preisverlauf löschbar
- zeitgesteuerte oder vollautomatische Willhaben-Suche
- Preisverlauf, Änderungsstatus sowie Offline-/Wieder-online-Erkennung
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

Jede Hausakte kann direkt über das Mülleimer-Symbol abgelehnt werden. Sie verschwindet aus der Hauptübersicht und bleibt im Ablehnungsarchiv erhalten. Dort kann sie wiederhergestellt oder endgültig inklusive Projektdateien gelöscht werden.

## Suchprofile verwalten

Pfad:

```text
Einstellungen
→ Suchprofile
```

Oben rechts legt **＋** ein neues Suchprofil an. Jedes bestehende Profil hat eine eigene Löschaktion.

Beim Löschen eines Suchprofils werden gelöscht:

- das Profil,
- seine Kandidaten,
- deren Preisverlauf,
- deren Änderungsereignisse.

Bereits angelegte Hausakten bleiben erhalten.

## Kandidaten-Lifecycle

HausCheck unterscheidet jetzt:

```text
new          neu gefunden
review       manuell prüfen
changed      relevante Daten geändert
reactivated  nach Offline-Status wieder online
offline      in zwei erfolgreichen Suchläufen nicht mehr gefunden
imported     als Hausakte angelegt
rejected     abgelehnt
```

Ein Suchlauf mit null Treffern setzt keine Inserate auf offline, weil dies auch eine vorübergehende Portalstörung sein kann. Erst zwei erfolgreiche Suchläufe ohne erneuten Fund markieren einen Kandidaten als offline.

Wird ein Offline-Inserat wieder gefunden, erscheint es als **wieder online**.

## Preisverlauf und Änderungen

Je Kandidat werden Preisbeobachtungen und relevante Änderungen gespeichert. Überwacht werden:

- Preis,
- Titel,
- Wohnfläche,
- Grundstücksfläche,
- HWB,
- Vorschaubild.

Preisänderungen werden beispielsweise so angezeigt:

```text
389.000 € → 359.000 € (-7,7 %)
```

Zusätzlich sind Datum, frühere Preise und Änderungsereignisse in der Kandidatenkarte einsehbar.

Hat ein bereits importiertes Objekt relevante Änderungen, zeigt die Hauskarte **Neue Analyse empfohlen**. Nach einem erfolgreichen neuen Analyseimport wird dieser Hinweis automatisch zurückgesetzt.

## HWB- und Dezimalwerte

Für HWB und fGEE gelten Punkt und Komma als Dezimaltrennzeichen:

```text
306.1  → 306,1
306,1  → 306,1
```

HausCheck priorisiert Energiekennzahlen aus Tabellen, Definitionslisten und Wertelisten. Erst wenn dort kein Wert gefunden wird, wird der allgemeine Seitentext verwendet.

## Produktiver Ablauf

```text
Willhaben-Suche
→ Kandidat speichern und filtern
→ Preis- und Änderungsverlauf aktualisieren
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

Das Suchprofil läuft nur über die Lupe.

### Automatisch suchen, manuell importieren

HausCheck aktualisiert die Kandidatenliste zeitgesteuert. Eine Hausakte wird erst nach Bestätigung angelegt.

### Automatisch suchen und importieren

HausCheck importiert Kandidaten mit Status `new`, `changed` oder `reactivated`, sofern:

- noch keine Hausakte vorhanden ist,
- der konfigurierte Mindestscore erreicht wird,
- der Kandidat nicht abgelehnt oder offline ist.

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
