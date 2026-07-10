# HausCheck Pro Add-on

## Start

Nach der Installation das Add-on starten und über den Home-Assistant-Ingress öffnen.

## Aktueller Funktionsumfang v0.5.3

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
- Vorschaubild je Kandidat bevorzugt aus der Portal-/Willhaben-Übersicht
- mobilfreundliche Kandidaten-Karten statt breiter Tabelle
- Ladeanzeige mit Spinner und Aktionstext
- Deduplizierung über Willhaben-Inserat-ID
- regelbasierte Erstbewertung / Score je Kandidat und Hausakte
- geschützte ChatGPT/API/MCP-Bridge für externe Analyse
- Home-Assistant-Proxy für Nabu-Casa-Zugriff über `/api/hauscheck/...`

## Zentrale Suchprofile verwenden

1. In HausCheck auf **Suchprofile** klicken.
2. Name, zentrale Kriterien und Willhaben-PLZ/areaIds speichern.
3. Die Willhaben-URL kann leer bleiben.
4. Profil öffnen und **Suchprofil jetzt starten** klicken.
5. Kandidaten anhand Vorschaubild, Fakten und Score prüfen.
6. Kandidaten einzeln importieren. Bilder werden beim Import automatisch geladen.

Die Kandidatenansicht ist für Mobilgeräte optimiert: Bild, Titel, Fakten, Status, Score und Import-Schaltfläche stehen in einer Immobilien-Karte.

Die zentrale Logik lautet:

```text
Profil-Kriterien = Wahrheit
Portalquelle = automatisch erzeugt oder optional manuell
HausCheck-Filter = finale Kontrolle
HausCheck-Score = schnelle Priorisierung
ChatGPT-Bridge = externe Analyse / Bildanalyse
Home-Assistant-Proxy = Nabu-Casa-Zugriff
```

## Nabu-Casa-Zugriff über Home Assistant Proxy

Zusätzlich zum Add-on enthält das Repository eine Custom Integration:

```text
custom_components/hauscheck_proxy/
```

Diese Integration registriert Home-Assistant-API-Endpunkte:

```text
GET  /api/hauscheck/health
GET  /api/hauscheck/houses
GET  /api/hauscheck/houses/{house_id}
GET  /api/hauscheck/search-profiles
GET  /api/hauscheck/search-profiles/{profile_id}/candidates
GET  /api/hauscheck/mcp
POST /api/hauscheck/mcp
```

Dadurch kann der Zugriff über deine Nabu-Casa-URL laufen:

```text
https://<deine-instanz>.ui.nabu.casa/api/hauscheck/health
```

Nach außen gilt die Home-Assistant-Authentifizierung, also z. B. ein Long-Lived Access Token. Nach innen leitet der Proxy mit dem HausCheck-`api_token` an das Add-on weiter.

### Installation der Custom Integration

1. Ordner kopieren:

```text
custom_components/hauscheck_proxy
→ /config/custom_components/hauscheck_proxy
```

2. In den HausCheck-Add-on-Optionen einen langen `api_token` setzen.

3. In `configuration.yaml` ergänzen:

```yaml
hauscheck_proxy:
  base_url: http://127.0.0.1:8088
  token: "DEIN_HAUSCHECK_API_TOKEN"
  timeout: 120
```

4. Home Assistant neu starten.

5. Mit lokalem HA-Zugriff testen:

```bash
curl -H "Authorization: Bearer HA_LONG_LIVED_TOKEN" \
http://HOMEASSISTANT-IP:8123/api/hauscheck/health
```

6. Danach über Nabu Casa testen:

```bash
curl -H "Authorization: Bearer HA_LONG_LIVED_TOKEN" \
https://<deine-instanz>.ui.nabu.casa/api/hauscheck/health
```

Wenn `127.0.0.1:8088` aus Home Assistant nicht erreichbar ist, muss `base_url` auf die erreichbare interne Adresse des Add-ons angepasst werden.

## ChatGPT-/MCP-Bridge im Add-on

Die Bridge ist standardmäßig deaktiviert. Sie wird erst aktiv, wenn in den Add-on-Optionen ein `api_token` gesetzt ist.

Interne Add-on-Endpunkte:

```text
GET  /api/chatgpt/health
GET  /api/chatgpt/houses
GET  /api/chatgpt/houses/{house_id}
GET  /api/chatgpt/search-profiles
GET  /api/chatgpt/search-profiles/{profile_id}/candidates
POST /mcp
GET  /mcp
```

Authentifizierung intern:

```text
Authorization: Bearer <api_token>
```

oder:

```text
X-HausCheck-Token: <api_token>
```

MCP-Tools:

```text
list_houses
get_house
get_house_images
list_search_profiles
get_candidates
```

`get_house_images` liefert lokale Hausbilder als Bildinhalte zurück. Damit ist eine Bildanalyse durch ein angebundenes Modell grundsätzlich möglich.

## Vorschaubilder

HausCheck versucht das Vorschaubild direkt aus der Portal-/Willhaben-Übersicht zu übernehmen. Das entspricht eher dem Bild, das auch auf der Suchergebnisseite sichtbar ist.

Wenn dort kein Bild erkannt wird, bleibt die Detailseite als Fallback.

## Regelbasierte Erstbewertung

Der Score bewertet aktuell nur vorhandene Daten aus dem Inserat:

- Preis
- Wohnfläche
- Grundstück
- HWB
- Kandidatenstatus: neu / prüfen / gefiltert / importiert

Ergebnis:

```text
82-100  sehr interessant
68-81   interessant
50-67   prüfen
0-49    kritisch
```

Zusätzlich wird eine Bewertungssicherheit angezeigt:

```text
hoch    mehrere wichtige Werte vorhanden
mittel  einige Werte vorhanden
niedrig zu viele Werte fehlen
```

Wichtig: Der Score ist noch keine Marktwertschätzung. Fehlende Werte werden nicht erfunden.

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
