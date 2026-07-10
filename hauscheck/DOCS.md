# HausCheck Pro Add-on

## Start

Nach der Installation das Add-on starten und über den Home-Assistant-Ingress öffnen.

## Aktueller Funktionsumfang v0.2

- Hausakten-Dashboard
- Direktlink-Import
- konservativer Willhaben-Parser
- SQLite-Datenbank unter `/share/hauscheck/hauscheck.db`
- lokale Medienablage unter `/share/hauscheck/projects/`
- Bild-URL-Erkennung und Download
- Medienfilter gegen Logos, Icons und Duplikate
- manuelle Medien-Uploads
- Analysebriefing pro Hausakte
- Suchlauf-MVP für Willhaben-Suchergebnis-URLs
- Kandidatenliste mit Einzelimport

## Suchlauf verwenden

1. In Willhaben eine Suche mit deinen Kriterien öffnen.
2. Die Suchergebnis-URL kopieren.
3. In HausCheck auf **Suchlauf starten** klicken.
4. URL einfügen und auslesen.
5. Kandidaten einzeln importieren.

Wichtig:

- Suchseiten werden nicht als Hausakten gespeichert.
- Nur echte Inserat-Direktlinks werden als Kandidaten angezeigt.
- Wenn keine Kandidaten erscheinen, wurde die Seite vermutlich dynamisch geladen oder durch Willhaben blockiert.

## Hinweise

Dies ist eine frühe MVP-Version. Die Parser sind bewusst konservativ:

- fehlende Werte bleiben leer
- Grundstück wird nur aus expliziten Grundstücksfeldern übernommen
- ohne genaue Adresse erfolgt keine belastbare Lageprüfung
- aktuell keine Captcha-/Login-Umgehung

## Datenablage

```text
/share/hauscheck/
├── hauscheck.db
├── projects/
└── logs/
```
