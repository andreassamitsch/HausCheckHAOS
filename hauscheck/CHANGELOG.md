# Changelog

## 0.4.1

- Willhaben-Such-URL ist beim Suchprofil nicht mehr Pflicht
- automatische Willhaben-Quelle wird aus zentralen Kriterien erzeugt
- Standardquelle nutzt `areaId=60351`, `sort=1`, `rows=30`, `page=1`
- `PRICE_TO` wird aus der harten Preisgrenze gesetzt
- `ESTATE_SIZE/LIVING_AREA_FROM` wird aus der Mindestwohnfläche gesetzt
- manuelle Willhaben-URL bleibt optional für Spezialfälle wie spätere Umkreissuche

## 0.4.0

- Suchprofile um zentrale Kriterien erweitert
- Zielpreis, harte Preisgrenze, Mindestwohnfläche und Wunsch-Grundstück speicherbar
- Regionen, Ausschluss-/Prüfbegriffe, HWB-Grenzen und Ölheizungsregel ergänzt
- Suchlauf prüft Kandidaten anhand der zentralen Kriterien
- Kandidatenstatus erweitert: neu, prüfen, gefiltert, importiert
- Kandidaten speichern grobe Fakten: Preis, Wohnfläche, Grundstück und HWB
- Kandidaten zeigen Filtergründe direkt in der Profilansicht
- Portal-URL bleibt als technische Quelle erhalten, Kriterien bleiben zentral

## 0.3.0

- Suchprofile dauerhaft in SQLite speichern
- mehrere Willhaben-Suchprofile möglich
- Suchprofile aus Dashboard und Suchprofilseite starten
- gefundene Kandidaten werden persistent gespeichert
- Kandidatenstatus: neu oder importiert
- Kandidatenliste bleibt nach Neustart erhalten
- Import aus Kandidatenliste markiert passende Kandidaten automatisch als importiert

## 0.2.0

- Dashboard-Button „Suchlauf starten“ ergänzt
- neue Seite `/search` für Willhaben-Suchergebnis-URLs
- Willhaben-Suchseiten werden ausgelesen
- echte Inserat-Direktlinks werden extrahiert
- Kandidatenliste mit Status „neu“ oder „bereits importiert“
- Kandidaten können einzeln direkt importiert werden
- Suchseiten werden nicht als Objekte gespeichert

## 0.1.2

- Willhaben-Bild-URL-Erkennung auf Galerie-Kandidaten fokussiert
- Bild-URLs werden normalisiert und doppelte URLs werden vermieden
- Medien erhalten Content-Hash, Bildbreite, Bildhöhe und Dateigröße
- Doppelte Bildinhalte werden beim Download übersprungen
- kleine Logos, Icons und UI-Grafiken werden als `skipped` markiert
- Button „Medien bereinigen“ für bereits importierte Objekte ergänzt
- Medienübersicht zeigt geladene, offene, übersprungene und fehlerhafte Medien

## 0.1.1

- Links und Formularziele für Home-Assistant-Ingress auf relative Pfade umgestellt
- Redirects nach Import, Medien-Download und Upload ingress-kompatibel gemacht
- Anzeige fehlgeschlagener Medien-Downloads ergänzt

## 0.1.0

- Initiales HAOS Add-on Fundament
- FastAPI Weboberfläche mit Ingress
- SQLite-Speicher unter `/share/hauscheck`
- Hausakten-Dashboard
- Direktlink-Import
- konservativer Willhaben-Parser
- Medienliste, Bilddownload und manueller Upload
- Analysebriefing pro Hausakte
