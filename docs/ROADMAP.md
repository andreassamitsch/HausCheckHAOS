# HausCheckHAOS – Roadmap

Version: 0.1  
Status: Entwurf

## Leitlinie

HausCheckHAOS wird zuerst als stabile Home-Assistant-Anwendung aufgebaut. Die KI-Bewertung kommt erst, wenn Hausakten, Medien und Datenqualität zuverlässig funktionieren.

## v0.1 – Fundament

Ziel: Add-on installierbar und in Home Assistant sichtbar.

Umfang:

- gültiges Home-Assistant Add-on Repository
- Add-on `hauscheck`
- FastAPI Backend
- einfache Weboberfläche
- HA Ingress aktivieren
- persistenter Speicher unter `/share/hauscheck`
- SQLite-Datenbank
- Grundkonfiguration
- Suchprofil lesen/speichern
- Logging

Erfolgskriterien:

- Add-on erscheint im HA Add-on Store
- Add-on startet ohne Fehler
- Oberfläche ist über Home Assistant erreichbar
- Daten bleiben nach Neustart erhalten

## v0.2 – Hausakten und Dashboard

Ziel: Objekte strukturiert anzeigen und verwalten.

Umfang:

- Dashboard mit neuen Objekten, Favoriten, Beobachtung, Archiv
- Hausakte anlegen
- Objektliste mit Kartenansicht
- Detailseite
- Status setzen: neu, beobachten, Favorit, abgelehnt, Archiv
- Notizen
- Entscheidungslog

Erfolgskriterien:

- Ein Objekt kann manuell angelegt und dauerhaft gespeichert werden
- Objektstatus und Notizen bleiben erhalten
- Darstellung ist am Handy gut nutzbar

## v0.3 – Willhaben MVP

Ziel: erster stabiler Portaladapter.

Umfang:

- Willhaben Such-URL aus Suchprofil erzeugen
- Suchseiten abrufen
- echte Direktlinks extrahieren
- Detailseiten abrufen
- Preis, Wohnfläche, Grundstück, Ort, HWB, fGEE, Heizung soweit möglich parsen
- Parserdiagnose speichern
- keine Werte erfinden
- keine Suchseiten als Objekte speichern

Erfolgskriterien:

- Suchlauf findet reale Willhaben-Detailseiten
- Grundstück wird nur aus expliziter Grundstücksangabe übernommen
- jedes Feld zeigt Herkunft und Confidence

## v0.4 – Medien-Collector

Ziel: Bilder und Dokumente lokal sichern.

Umfang:

- Bild-URLs aus HTML/JSON extrahieren
- Bilder herunterladen
- Thumbnails erzeugen
- PDFs speichern
- manuelle Uploads
- Medienmanifest
- Fehler je Medium speichern

Erfolgskriterien:

- Bilder werden pro Hausakte lokal gespeichert
- doppelte Bilder werden vermieden
- Medien sind in der Detailansicht sichtbar

## v0.5 – Automatische Suche

Ziel: HausCheck arbeitet täglich automatisch.

Umfang:

- Scheduler
- Suchläufe nach Suchprofil
- neue Objekte erkennen
- Preisänderungen erkennen
- offline Inserate markieren
- Suchlauf-Diagnose

Erfolgskriterien:

- tägliche Suche läuft automatisch
- neue Treffer werden sauber dokumentiert
- ausgeschlossene Treffer haben Gründe

## v0.6 – Weitere Portale

Ziel: Marktabdeckung erhöhen.

Priorität:

1. ImmobilienScout24 Österreich
2. Immowelt
3. Immobilien.net
4. RE/MAX
5. Raiffeisen Immobilien
6. sREAL
7. Peisser Immobilien

Erfolgskriterien:

- jeder Adapter ist einzeln aktivierbar
- Fehler in einem Portal blockieren nicht das ganze System
- Direktlinks werden dedupliziert

## v0.7 – Lageanalyse

Ziel: erste automatische Lageprüfung.

Umfang:

- Geocoding, falls Adresse vorhanden
- OSM/Overpass Distanzen
- B76/B69 und Hauptstraßen
- Bahn
- Sportanlagen
- Gewerbe
- Gewässer
- Kartenlinks
- Status: gesichert, abgeleitet, unsicher, nicht prüfbar

Erfolgskriterien:

- keine harte Lageaussage ohne Adresse
- Distanzprüfungen werden mit Quelle gespeichert
- Lagewarnungen erscheinen in der Hausakte

## v0.8 – Bewertung und Fair Value regelbasiert

Ziel: erste nachvollziehbare Bewertung ohne KI-Blackbox.

Umfang:

- Scoremodell
- Kaufchance
- Fair-Value-Rechner
- Investitionspuffer
- Energie-/HWB-Regeln
- Preisempfehlung
- Zu- und Abschläge

Erfolgskriterien:

- Bewertung ist erklärbar
- HWB > 300 erzeugt immer Warnung und Investitionspuffer
- fehlende Daten senken Confidence statt Fake-Werte zu erzeugen

## v0.9 – KI optional

Ziel: KI als Erweiterung, nicht als Voraussetzung.

Umfang:

- OpenAI API optional
- Textbewertung
- Bildbewertung ausgewählter Medien
- Sanierungsrisiko
- Verhandlungsargumente
- Besichtigungsfragen
- Kostenkontrolle

Erfolgskriterien:

- System läuft ohne API-Key weiter
- API-Key wird sicher gespeichert und nie exportiert
- KI-Ergebnisse sind als Einschätzung gekennzeichnet

## v1.0 – Alltagstaugliche Version

Ziel: stabiler persönlicher Immobilienassistent.

Umfang:

- mehrere Portale
- tägliche Suche
- Hausakten
- Medienarchiv
- Dashboard
- Favoriten
- Bewertungsmodell
- Benachrichtigungen
- Export/Backup

Erfolgskriterien:

- tägliche Nutzung am Handy über Home Assistant möglich
- relevante neue Objekte werden zuverlässig angezeigt
- uninteressante Objekte werden begründet ausgeschlossen
- Top-Chancen sind nachvollziehbar priorisiert
