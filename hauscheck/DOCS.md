# HausCheck Pro Add-on

## Start

Nach der Installation das Add-on starten und über den Home-Assistant-Ingress öffnen.

## Aktueller Funktionsumfang v0.4.6

- Hausakten-Dashboard
- Direktlink-Import
- konservativer Willhaben-Parser
- SQLite-Datenbank unter `/share/hauscheck/hauscheck.db`
- lokale Medienablage unter `/share/hauscheck/projects/`
- Bild-URL-Erkennung und automatischer Bilddownload beim Import
- Medienfilter gegen Logos, Icons und Duplikate
- manuelle Medien-Uploads
- Analysebriefing pro Hausakte
- zentrale Suchprofile mit Kriterien
- automatisch erzeugte Willhaben-Suchquellen über eine oder mehrere PLZ/areaIds
- optionale manuelle Willhaben-Such-URL für Spezialfälle, z. B. Umkreis
- persistente Kandidatenliste mit Einzelimport
- Kandidaten-Vorprüfung anhand Preis, Wohnfläche, Grundstück und HWB
- Vorschaubild je Kandidat
- mobilfreundliche Kandidaten-Karten statt breiter Tabelle
- Ladeanzeige mit Spinner und Aktionstext
- Deduplizierung über Willhaben-Inserat-ID

## Zentrale Suchprofile verwenden

1. In HausCheck auf **Suchprofile** klicken.
2. Name, zentrale Kriterien und Willhaben-PLZ/areaIds speichern.
3. Die Willhaben-URL kann leer bleiben.
4. Profil öffnen und **Suchprofil jetzt starten** klicken.
5. Kandidaten anhand Vorschaubild und Fakten prüfen.
6. Kandidaten einzeln importieren. Bilder werden beim Import automatisch geladen.

Die Kandidatenansicht ist für Mobilgeräte optimiert: Bild, Titel, Fakten, Status und Import-Schaltfläche stehen in einer Immobilien-Karte.

Die zentrale Logik lautet:

```text
Profil-Kriterien = Wahrheit
Portalquelle = automatisch erzeugt oder optional manuell
HausCheck-Filter = finale Kontrolle
```

## Automatische Willhaben-Quelle

Wenn keine Willhaben-URL eingetragen wird, erzeugt HausCheck pro PLZ/areaId eine Willhaben-Suche nach diesem Muster:

```text
https://www.willhaben.at/iad/immobilien/haus-kaufen/haus-angebote
?areaId=<PLZ oder areaId>
&page=1
&PRICE_TO=<harte Preisgrenze>
&ESTATE_SIZE/LIVING_AREA_FROM=<Mindestwohnfläche>
```

Beispiel Wies:

```text
areaId=8551
```

Mehrere PLZ/areaIds können kommagetrennt eingetragen werden:

```text
8551,8552,8544,8553
```

Die frühere Maske „Regionen / Orte“ wurde entfernt. Für Willhaben steuert jetzt **PLZ / areaId** die Suche. Die lokale Textprüfung über Orte war zu unzuverlässig und wird später sauber über Portaladapter/Geo-Daten ersetzt.

Die Umkreissuche mit `lat`, `lon` und `sfId` ist noch nicht automatisiert. Dafür kann vorerst weiterhin eine manuelle Willhaben-URL als Vorlage eingetragen werden.

## Ladeanzeige

Bei länger laufenden Aktionen zeigt HausCheck einen Ladehinweis mit Spinner:

- Suchprofil starten
- Inserat importieren und Bilder laden
- Medien erneut herunterladen
- Medien bereinigen
- Datei hochladen

## Kandidatenstatus

- `neu`: Kriterien aktuell erfüllt
- `prüfen`: nicht ausgeschlossen, aber mit Warnung
- `gefiltert`: harte Kriterien nicht erfüllt
- `importiert`: bereits als Hausakte vorhanden

## Import und Medien

Beim Import aus der Kandidatenliste oder per Direktlink werden Bilder und PDFs automatisch geladen.

Der Button **Medien erneut herunterladen** bleibt als Retry-Funktion erhalten, falls einzelne Medien beim ersten Versuch fehlschlagen.

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
