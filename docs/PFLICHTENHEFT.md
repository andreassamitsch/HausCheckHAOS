# HausCheckHAOS – Pflichtenheft

Version: 0.1  
Status: Entwurf  
Projektziel: Persönlicher Immobilien-Entscheidungsassistent für Home Assistant

## 1. Ziel und Abgrenzung

HausCheckHAOS soll die private Haussuche in der Südweststeiermark automatisieren und strukturieren. Das System soll nicht nur Inserate finden, sondern aus jedem relevanten Objekt eine dauerhafte Hausakte erzeugen, Medien sichern, Risiken dokumentieren und später eine nachvollziehbare Bewertung unterstützen.

### Hauptziel

Der Nutzer soll täglich nur jene Immobilien sehen, die nach persönlichen Kriterien tatsächlich prüfenswert sind.

### Nicht-Ziel in der ersten Ausbaustufe

- keine vollautomatische Kaufentscheidung
- keine verbindliche Sachverständigenbewertung
- keine rechtliche Prüfung
- keine garantierte exakte Lagebestimmung ohne Adresse
- keine Umgehung von Logins, Captchas oder technischen Schutzmaßnahmen

## 2. Zielumgebung

- Home Assistant OS / HAOS
- Installation als Home-Assistant Add-on Repository
- Bedienung direkt über Home Assistant Oberfläche / Ingress
- Nutzung am Android-Handy über Home Assistant App oder Browser
- Persistente Daten unter `/share/hauscheck`

## 3. Kernmodule

### 3.1 Suchprofile

Suchprofile enthalten persönliche Suchkriterien.

Pflichtfelder:

- Name des Suchprofils
- Zielregionen
- Preisobergrenze
- Mindestwohnfläche
- bevorzugte Grundstücksgröße
- bevorzugte Baujahre
- Energieanforderungen
- Heizungspräferenzen
- Ausschlusskriterien
- Zeitplan für automatische Suche

Startprofil:

- Südweststeiermark
- Bezirk Deutschlandsberg
- Fokus: Wies, Eibiswald, Oberhaag, Hörmsdorf, Pölfing-Brunn, Bad Schwanberg, Frauental und Umgebung
- Preis bis ca. 380.000 €, optional bis 400.000 € als Grenzfall
- Wohnfläche ab ca. 130 m²
- Grundstück bevorzugt ab ca. 700 m²
- keine direkte Lage an B76/B69 oder vergleichbaren Durchzugsstraßen
- Ölheizung nur bei sehr gutem Gesamtpaket
- keine billigen Sanierungsfälle, wenn Gesamtinvestition unattraktiv wird

### 3.2 Portaladapter

Jedes Immobilienportal wird als eigener Adapter umgesetzt.

Erste Zielportale:

1. Willhaben
2. ImmobilienScout24 Österreich
3. Immowelt
4. Immobilien.net
5. RE/MAX
6. Raiffeisen Immobilien
7. sREAL
8. Peisser Immobilien

Adapter liefern normalisierte Kandidaten mit:

- Quelle
- Direktlink
- Externe Inserat-ID
- Titel
- Preis
- Wohnfläche
- Grundstück
- Ort / Adresse falls vorhanden
- Energiekennwerte
- Heizung
- Beschreibung
- Medienlinks
- Parserdiagnose

Wichtig:

- Suchseiten dürfen nicht als Objekte gespeichert werden.
- Nur echte Inserat-Direktlinks werden als Kandidaten verarbeitet.
- Fehlende Werte bleiben `null`; sie dürfen nicht erfunden werden.
- Grundstück darf niemals aus Wohnfläche abgeleitet werden.

### 3.3 Hausakte

Jedes Objekt erhält eine dauerhafte Hausakte.

Die Hausakte enthält:

- Stammdaten
- Portalquellen
- Preisverlauf
- Medien
- Lageinformationen
- Bewertungen
- Notizen
- offene Fragen
- Makler-/Kontaktinformationen
- Besichtigungen
- Entscheidungsverlauf

Ziel: Ein Haus bleibt auch dann als dasselbe Objekt erkennbar, wenn ein Inserat geändert, neu eingestellt oder von einem anderen Portal gefunden wird.

### 3.4 Medienverwaltung

Das System speichert Medien lokal:

- Inserat-HTML
- Originalbilder
- Thumbnails
- PDFs
- Videos, sofern öffentlich erreichbar
- Video-Frames
- Screenshots
- Medienmanifest

Regeln:

- Medien werden pro Hausakte versioniert.
- Doppelte Bilder sollen erkannt werden.
- Wenn Bilder nicht heruntergeladen werden können, wird der Grund gespeichert.
- Bildquellen werden dokumentiert.

### 3.5 Lageanalyse

Die Lageanalyse trennt strikt zwischen Fakten, Ableitungen und KI-Einschätzungen.

Stufen:

1. Gesicherte Angaben
   - exakte Adresse
   - Koordinaten
   - PLZ/Gemeinde
   - Kataster-/Widmungsdaten, sofern verfügbar

2. Automatisch geprüft
   - OSM-Distanzen
   - Hauptstraßen
   - Bahnlinien
   - Sportplätze
   - Gewerbe
   - Gewässer
   - Hang / Höhenmodell

3. Aus Fotos plausibilisiert
   - Aussicht
   - Hangrichtung
   - Nachbargebäude
   - sichtbare Straßen
   - Stromleitungen
   - Geländesprünge

4. KI-Einschätzung
   - nur als unsichere Plausibilitätsbewertung
   - niemals als gesicherte Adresse

### 3.6 Bewertung

Bewertung erfolgt mehrdimensional:

- Wohnqualität
- Preis-Leistung
- Lage
- Energie
- Sanierungsrisiko
- Familiengeeignetheit
- Verhandlungspotenzial
- Kaufchance

Jeder Score muss begründet werden.

Fair-Value-Ausgabe:

- realistischer Marktwert
- geschätzter Investitionsbedarf
- empfohlener Zielpreis
- erstes Angebot
- Schmerzgrenze
- Preis, über dem nicht gekauft werden sollte

### 3.7 Confidence / Bewertungssicherheit

Jede Aussage erhält eine Sicherheit:

- `verified` – explizit im Inserat oder aus verlässlicher Quelle
- `derived` – aus Karten/Geodaten abgeleitet
- `estimated` – plausibilisierte Schätzung
- `unknown` – nicht belastbar prüfbar

Die Oberfläche muss diese Sicherheit sichtbar machen.

## 4. Dashboard

Die Anzeige erfolgt direkt in Home Assistant.

Bereiche:

- Neue Treffer
- Top Chancen
- Favoriten
- Beobachtung
- Archiv
- Ausgeschlossene Objekte
- Suchläufe / Diagnose

Objektkarten zeigen:

- Hauptbild
- Titel
- Ort
- Preis
- Wohnfläche
- Grundstück
- Score
- Kaufchance
- Status
- wichtigste Warnung

Detailansicht:

- Bildergalerie
- Stammdaten
- Bewertung
- Lage
- Medien
- Notizen
- Historie
- offene Fragen
- Links zum Originalinserat

## 5. Automatisierung

Geplante Automationen:

- tägliche Suche
- Preisänderungen erkennen
- neue Medien erkennen
- alte/offline Inserate markieren
- Top-Kandidaten melden
- tägliche Entscheidungsübersicht erzeugen

Benachrichtigungen sollen nur bei wirklich relevanten Objekten gesendet werden.

## 6. Technische Leitlinien

- Backend: Python / FastAPI
- Datenbank: SQLite
- Oberfläche: Web UI über HA Ingress
- Add-on: Home Assistant Add-on Repository
- Speicher: `/share/hauscheck`
- Portaladapter modular
- Medien lokal speichern
- KI optional, später austauschbar
- keine Secrets im Repository

## 7. Qualitätsregeln

- Keine erfundenen Daten.
- Keine Suchergebnislinks als Objekte.
- Jede Parserentscheidung muss nachvollziehbar sein.
- Jede Bewertung muss begründet sein.
- Unsichere Lage darf nicht als gesichert dargestellt werden.
- Lieber weniger Treffer anzeigen als falsche Top-Treffer.

## 8. MVP-Ziel

Version 0.1 gilt als erfolgreich, wenn:

- Add-on in Home Assistant installierbar ist
- Ingress/Weboberfläche funktioniert
- Hausakten angelegt werden können
- Willhaben-Direktlinks importiert werden können
- HTML und Bilder gespeichert werden
- eine einfache Objektliste und Detailansicht vorhanden ist
- Daten persistent unter `/share/hauscheck` liegen
