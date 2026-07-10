# HausCheck Pro Add-on

## Start

Nach der Installation das Add-on starten und über den Home-Assistant-Ingress öffnen.

## Aktueller Funktionsumfang v0.3

- Hausakten-Dashboard
- Direktlink-Import
- konservativer Willhaben-Parser
- SQLite-Datenbank unter `/share/hauscheck/hauscheck.db`
- lokale Medienablage unter `/share/hauscheck/projects/`
- Bild-URL-Erkennung und Download
- Medienfilter gegen Logos, Icons und Duplikate
- manuelle Medien-Uploads
- Analysebriefing pro Hausakte
- gespeicherte Suchprofile für Willhaben-Suchergebnis-URLs
- persistente Kandidatenliste mit Einzelimport

## Suchprofile verwenden

1. In Willhaben eine Suche mit deinen Kriterien öffnen.
2. Die Suchergebnis-URL kopieren.
3. In HausCheck auf **Suchprofile** klicken.
4. Name und Such-URL speichern.
5. Profil öffnen und **Suchprofil jetzt starten** klicken.
6. Kandidaten einzeln importieren.

Beispiele für Suchprofile:

- Wies/Eibiswald bis 380k
- Oberhaag/Obergreith Grenzfälle
- Deutschlandsberg größere Grundstücke
- Preisgrenze 400k als Beobachtung

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

## Datenablage

```text
/share/hauscheck/
├── hauscheck.db
├── projects/
└── logs/
```
