# Changelog

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
