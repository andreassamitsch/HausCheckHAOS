# HausCheck Pro Add-on

## Aktueller Funktionsumfang v0.11.1

HausCheck verwaltet Immobilien als Hausakten, sucht passende Willhaben-Inserate, lädt Medien, übergibt Analysepakete über GitHub an ChatGPT und importiert die fertige KI-Bewertung automatisch zurück.

Neu in 0.11.1:

- interne Links, Formulare und Bildpfade funktionieren unter Home-Assistant-Ingress
- der 404-Fehler beim Anlegen einer Hausakte aus einem Suchkandidaten ist behoben
- jede Seite besitzt ein Symbol zum Neuladen der aktuell sichtbaren Seite
- die fachliche Datenaktualisierung heißt zur Unterscheidung **Inserat neu einlesen**

## Navigation

Auf Mobilgeräten steht unten eine feste Navigation bereit:

```text
Hausakten · Suche · Abgelehnt · Einstellungen
```

Im Kopf jeder Seite befindet sich ein Refresh-Symbol. Es lädt ausschließlich die aktuell geöffnete Seite neu. Es startet keine Suche und keine Analyse.

## Hausaktenübersicht

Die Startseite zeigt aktive Hausakten mit Titelbild, Titel, Lage, Bewertung, Pipeline-Status, Preis, Wohnfläche und Grundstück.

Oberhalb der Hausakten erscheint ein direkter Listenlink:

```text
X nicht importierte Suchkandidaten
```

Dieser öffnet die Kandidatenliste zum Prüfen, Importieren oder Ablehnen.

## Inserat neu einlesen

Die Aktion **Inserat neu einlesen** lädt alle zugeordneten Makler-Inserate erneut und aktualisiert:

- Inseratsdaten
- Quellen und Feldnachweise
- Bilder und PDFs
- Kandidatendaten
- Änderungszusammenfassung

Bei relevanten Änderungen wird eine neue KI-Analyse gestartet. Diese Funktion ist nicht mit dem Refresh-Symbol der Seite zu verwechseln.

## Zwei Hausakten zusammenführen

Die Funktion **Zusammenlegen** ist direkt in der oberen Aktionsleiste jeder Hausakte sichtbar. Die aktuell geöffnete Hausakte bleibt die Hauptakte.

Übernommen werden Inseratsquellen, Maklerbeschreibungen, Feldnachweise, Bilder, PDFs, Kandidatenzuordnungen, Preisverläufe, fehlende Stammdaten und frühere KI-Analysen. Vorhandene Werte der Hauptakte bleiben bestehen. Doppelte Medien werden anhand Datei-Hash oder Original-URL entfernt.

## Titelbild wählen

Über die Aktion **Titelbild** wird ein Galeriebild als Vorschaubild ausgewählt. Die normale Bildergalerie bleibt frei von zusätzlichen Schaltflächen. Über **Automatische Auswahl** kann die feste Auswahl aufgehoben werden.

## Hausakte bearbeiten

Die Aktion **Bearbeiten** öffnet ein eigenes Formular für Titel, Lage, Preis, Flächen, Zimmer, Baujahr, HWB, fGEE, Heizung und Notizen.

## Suchprofile verwalten

Pfad:

```text
Einstellungen → Suchprofile
```

Bestehende Profile können vollständig bearbeitet werden: Name, Regionen, areaIds, Such-URL, Preis-, Flächen- und HWB-Grenzen, Ausschlussbegriffe, Heizungsregel, Status, Automatikmodus, Intervall, Trefferlimit und Auto-Import-Grenzen.

Neue Profile werden über **Neues Profil** angelegt. Beim Löschen eines Profils bleiben bereits angelegte Hausakten erhalten.

## Im Home-Assistant-Dashboard verlinken

1. **Einstellungen → Apps → HausCheck** öffnen.
2. Die Weboberfläche von HausCheck öffnen.
3. Den Browser-Pfad ab `/hassio/ingress/` kopieren.
4. Das gewünschte Dashboard bearbeiten und eine manuelle Karte hinzufügen.
5. Den kopierten Pfad als `navigation_path` verwenden.

Beispiel:

```yaml
type: button
name: HausCheck
icon: mdi:home-search
show_state: false
tap_action:
  action: navigate
  navigation_path: /hassio/ingress/ADDON_ID
```

`ADDON_ID` durch den tatsächlich kopierten Wert ersetzen. Die interne ID ist bei einem Add-on aus einem GitHub-Repository nicht zwingend nur `hauscheck`.

Optional kann HausCheck als Webseite eingebettet werden:

```yaml
type: iframe
url: /hassio/ingress/ADDON_ID/
aspect_ratio: 85%
```

Die Schaltflächenvariante ist auf Mobilgeräten meist robuster.

## Kandidaten-Lifecycle

```text
new          neu gefunden
review       manuell prüfen
changed      relevante Daten geändert
reactivated  wieder online
offline      in zwei erfolgreichen Suchläufen nicht gefunden
imported     als Hausakte angelegt
rejected     abgelehnt
```

Preisänderungen, erneute Veröffentlichungen und relevante Datenänderungen werden hervorgehoben und im Verlauf gespeichert.

## Bewertungssystem

Vor der KI-Analyse verwendet HausCheck eine regelbasierte Daten-Vorprüfung. Nach dem Import einer ChatGPT-Analyse wird `new_score` zur maßgeblichen Hauptbewertung.

Die KI-Auswertung kann einen fairen Kaufpreisbereich, Verhandlungsangebot, Zielpreis, Preisobergrenze, Investitionsposten und grobe Projektkosten enthalten. Die Kaufpreiseinschätzung ist kein Verkehrswertgutachten.

## HWB- und Dezimalwerte

```text
306.1 → 306,1
306,1 → 306,1
```

Strukturierte Werte aus Tabellen, Definitionslisten und Wertelisten haben Vorrang vor allgemeinem Seitentext.

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
```

## Hinweise

- Fehlende Werte bleiben leer und werden nicht erfunden.
- Ohne genaue Adresse erfolgt keine belastbare Lageprüfung.
- Captchas oder Login-Sperren werden nicht umgangen.
- Werbe- und KI-generierte Inseratbilder werden nicht als Zustandsnachweis verwendet.
