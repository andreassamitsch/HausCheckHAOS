# Changelog

## 0.5.8

- GitHub AI Exchange ergänzt
- neue Add-on-Optionen für GitHub-Repo, Branch, Token und Austauschpfade
- Hausakte enthält jetzt einen Bereich „GitHub AI Exchange“
- Button „Analysepaket nach GitHub exportieren“ lädt das ZIP nach `ai_exchange/exports/pending/<house_id>.zip`
- Button „GitHub-Ergebnisse importieren“ liest `ai_exchange/results/pending/.../hauscheck_analysis.json`
- importierte Ergebnisse werden lokal in der Hausakte gespeichert
- nach erfolgreichem Import wird das JSON nach `ai_exchange/results/done/<house_id>/...json` archiviert
- exportierte ZIPs und pending-Ergebnisse werden nach erfolgreichem Import aus GitHub aufgeräumt, wenn `github_cleanup_after_import` aktiv ist
- Hausdetailansicht wird robuster über eine eigene Route registriert und enthält die GitHub-Exchange-Karte

## 0.5.6

- Galerie korrigiert: großer Slider steht jetzt ganz oben in der Hausakte
- unterer Bereich „Bilder“ zeigt wieder alle Bilder einzeln als Raster wie zuvor
- Bildlinks öffnen weiterhin das jeweilige Bild groß in einem neuen Tab
- PDF-Import übernimmt Adressen nicht mehr automatisch in die Hausakte
- mögliche Adressen aus PDFs werden nur noch als `pdf_address_hint` in der Feldherkunft gespeichert
- Hinweistext beim Exposé-Upload angepasst, damit klar ist: Adresse manuell prüfen und eintragen

## 0.5.5

- Hausakten können jetzt gelöscht werden
- Löschen entfernt auch Quellen, Medien-Datenbankeinträge, Analysen und den Projektordner unter `/share/hauscheck/projects/<house_id>`
- Hausakten können manuell bearbeitet werden: Titel, Adresse/Lage, Adressstatus, Preis, Wohnfläche, Grundstück, Zimmer, Baujahr, HWB, fGEE, Heizung, Notizen und Portal-Vorschaubild
- Hauskarten verwenden bevorzugt das Portal-/Willhaben-Vorschaubild; lokale Bilder bleiben Fallback
- beim Import aus Kandidaten wird das Portal-Vorschaubild an die Hausakte übergeben
- Hausakte zeigt oben eine horizontale Galerie/Slider; Klick öffnet das Bild groß
- Exposé-PDF kann hochgeladen werden
- PDF-Text wird auf Adresse/Lage, Preis, Wohnfläche, Grundstück, Zimmer, Baujahr, HWB, fGEE und Heizung geprüft
- aus PDFs werden Bilder soweit technisch möglich extrahiert und der Hausakte hinzugefügt
- ChatGPT-Analysepaket fragt jetzt zusätzlich nach Adress-/Lagehinweisen mit Begründung und Sicherheit
- alter Analysebriefing-Button wurde aus der Hausakte entfernt

## 0.5.4

- manueller ChatGPT-Analyseworkflow ergänzt
- Button „Analysepaket exportieren“ in der Hausakte
- ZIP enthält `README_PROMPT.md`, `listing.json`, `evidence.json`, `current_score.json`, `import_schema.json`, `image_manifest.json` und verkleinerte Bilder unter `images/`
- Import von `hauscheck_analysis.json` oder ZIP mit enthaltener `hauscheck_analysis.json`
- importierte KI-Analyse wird pro Hausakte unter `/share/hauscheck/projects/<house_id>/analysis/hauscheck_analysis.json` gespeichert
- vorhandene Analyse wird vor Überschreiben automatisch gesichert
- KI-Score, Analysedatum, Zusammenfassung, Chancen und Risiken werden in der Hausakte angezeigt
- kein OpenAI-API-Key, kein MCP und keine Nabu-Casa-Verbindung für diesen Workflow nötig

## 0.5.3

- Home-Assistant-Proxy als Custom Integration `hauscheck_proxy` ergänzt
- Proxy-Endpunkte unter `/api/hauscheck/...` registriert
- Nabu-Casa-fähiger Zugriff über die Home-Assistant-API vorbereitet
- Proxy nutzt Home-Assistant-Authentifizierung nach außen und den HausCheck-`api_token` nach innen
- neue HA-Endpunkte: `/api/hauscheck/health`, `/api/hauscheck/houses`, `/api/hauscheck/houses/{house_id}`, `/api/hauscheck/search-profiles`, `/api/hauscheck/search-profiles/{profile_id}/candidates`, `/api/hauscheck/mcp`
- Add-on-Version auf 0.5.3 erhöht

## 0.5.2

- Variante C vorbereitet: ChatGPT/Home-Assistant-Bridge über API und MCP
- neuer geschützter Endpoint `/mcp` als Streamable-HTTP-MCP-MVP
- neue geschützte JSON-API unter `/api/chatgpt/...`
- neue Add-on-Option `api_token`
- MCP-Tools: `list_houses`, `get_house`, `get_house_images`, `list_search_profiles`, `get_candidates`
- `get_house_images` liefert lokale Hausbilder als Bildinhalte für Analysezwecke
- Start erfolgt über `app.bootstrap`, damit die ChatGPT-Bridge registriert wird
- API/MCP bleibt deaktiviert, solange kein `api_token` gesetzt ist

## 0.5.1

- Vorschaubilder werden bevorzugt aus der Portal-/Willhaben-Übersicht übernommen
- Suchseitenauswertung extrahiert nun Kandidaten mit Link, Titel und Übersichtsvorschaubild
- Detailseiten-Parser bleibt Fallback, falls in der Übersicht kein Bild erkannt wird
- bestehender Score bleibt unverändert

## 0.5.0

- Phase 7 Bewertung/Scoring vorgezogen
- regelbasierter Kandidaten-Score von 0 bis 100 ergänzt
- Bewertung direkt in der Kandidatenkarte sichtbar
- Bewertung auch in der Hausakte sichtbar
- Score nutzt nur vorhandene Inseratsdaten: Preis, Wohnfläche, Grundstück, HWB und Kandidatenstatus
- Bewertungssicherheit ergänzt: hoch, mittel oder niedrig
- keine Marktwertschätzung und keine erfundenen Werte
- Bewertungsklassen: sehr interessant, interessant, prüfen, kritisch

## 0.4.6

- Kandidatenansicht von Tabelle auf mobilfreundliche Immobilien-Karten umgestellt
- Layout schmaler und besser für Handy-Nutzung optimiert
- Vorschaubild, Titel, Status, Preis, Wohnfläche, Grundstück und HWB stehen jetzt direkt in einer Karte
- Import-Button ist mobil besser bedienbar
- globale Ladeanzeige mit Spinner ergänzt
- Ladehinweise für Suchlauf, Import, Medien-Download, Bereinigung und Upload ergänzt
- Tabellen bleiben nur noch für Nebenbereiche wie Quellen/Feldherkunft erhalten und sind horizontal scrollbar

## 0.4.5

- Feld „Regionen / Orte“ aus der Suchprofil-Maske entfernt, weil Willhaben jetzt über PLZ/areaIds gesucht wird
- Kandidaten werden zusätzlich über die Willhaben-Inserat-ID dedupliziert
- bestehende doppelte Kandidaten werden in der Profilansicht nur noch einmal angezeigt
- Kandidaten speichern ein Vorschaubild aus der Detailseite
- Kandidatenliste zeigt ein Vorschaubild je Inserat
- Import lädt Bilder und PDFs automatisch direkt mit
- „Medien herunterladen“ bleibt nur noch als Retry-Funktion erhalten
- Runtime-Patching im Startskript entfernt; Änderungen liegen wieder direkt in `app/main.py`

## 0.4.4

- neues Feld „Willhaben PLZ / areaIds“ im Suchprofil
- mehrere PLZ/areaIds möglich, z. B. `8551,8552,8544,8553`
- HausCheck erzeugt pro PLZ eine eigene Willhaben-Suchquelle
- Kandidaten aus mehreren PLZ-Suchen werden zusammengeführt und dedupliziert
- manuelle Willhaben-Such-URL bleibt weiterhin möglich und überschreibt die automatische PLZ-Suche
- bestehende automatische Profile werden weiter mit `8551` betrieben

## 0.4.3

- automatische Willhaben-Suche nutzt jetzt PLZ/areaId `8551` als Standard für Wies
- Willhaben-URL-Muster an die funktionierende PLZ-Suche angepasst
- bestehende automatisch erzeugte Profile mit `areaId=60351` werden beim Start auf `areaId=8551` migriert
- alte fehlerhafte Auto-URLs mit `ESTATE_SIZE/LIVING_AREA_FROM=1200` werden beim Start neu aus den Profilkriterien aufgebaut
- manuelle Umkreis-URLs mit `sfId`, `lat` oder `lon` bleiben unverändert

## 0.4.2

- Zahlenparser für Suchprofil-Kriterien korrigiert
- SQLite-REAL-Werte wie `120.0` werden nicht mehr fälschlich zu `1200`
- automatische Willhaben-URL setzt Mindestwohnfläche wieder korrekt, z. B. `ESTATE_SIZE/LIVING_AREA_FROM=120`
- deutsche Tausender-Schreibweise wie `400.000` bleibt weiterhin unterstützt

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
