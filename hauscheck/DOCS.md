# HausCheck Pro Add-on

## Start

Nach der Installation das Add-on starten und über den Home-Assistant-Ingress öffnen.

## Aktueller Funktionsumfang v0.4.1

- Hausakten-Dashboard
- Direktlink-Import
- konservativer Willhaben-Parser
- SQLite-Datenbank unter `/share/hauscheck/hauscheck.db`
- lokale Medienablage unter `/share/hauscheck/projects/`
- Bild-URL-Erkennung und Download
- Medienfilter gegen Logos, Icons und Duplikate
- manuelle Medien-Uploads
- Analysebriefing pro Hausakte
- zentrale Suchprofile mit Kriterien
- automatisch erzeugte Willhaben-Suchquelle
- optionale manuelle Willhaben-Such-URL für Spezialfälle
- persistente Kandidatenliste mit Einzelimport
- Kandidaten-Vorprüfung anhand Preis, Wohnfläche, Grundstück und HWB

## Zentrale Suchprofile verwenden

1. In HausCheck auf **Suchprofile** klicken.
2. Name und zentrale Kriterien speichern.
3. Die Willhaben-URL kann leer bleiben.
4. Profil öffnen und **Suchprofil jetzt starten** klicken.
5. Kandidaten prüfen und einzeln importieren.

Die zentrale Logik lautet:

```text
Profil-Kriterien = Wahrheit
Portalquelle = automatisch erzeugt oder optional manuell
HausCheck-Filter = finale Kontrolle
```

## Automatische Willhaben-Quelle

Wenn keine Willhaben-URL eingetragen wird, erzeugt HausCheck eine breite Willhaben-Suche nach diesem Muster:

```text
https://www.willhaben.at/iad/immobilien/haus-kaufen/haus-angebote
?sort=1
&rows=30
&page=1
&areaId=60351
&PRICE_TO=<harte Preisgrenze>
&ESTATE_SIZE/LIVING_AREA_FROM=<Mindestwohnfläche>
```

Die Umkreissuche mit `lat`, `lon` und `sfId` ist noch nicht automatisiert. Dafür kann vorerst weiterhin eine manuelle Willhaben-URL als Vorlage eingetragen werden.

Beispiele für Suchprofile:

- Wies/Eibiswald bis 380k, Grenzfälle bis 400k
- Oberhaag/Obergreith mit Grundstück ab 700 m²
- Deutschlandsberg größere Grundstücke
- Preisgrenze 400k als Beobachtung

## Kandidatenstatus

- `neu`: Kriterien aktuell erfüllt
- `prüfen`: nicht ausgeschlossen, aber mit Warnung
- `gefiltert`: harte Kriterien nicht erfüllt
- `importiert`: bereits als Hausakte vorhanden

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
