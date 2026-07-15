# Changelog

## 0.14.8

- GitHub-Dateien werden mit einem `httpx`-kompatiblen DELETE-Aufruf zuverlässig entfernt
- erfolgreich importierte Analyseergebnisse bleiben nicht mehr in `results/pending` hängen
- Ergebnisse für bereits gelöschte Hausakten werden einmalig nach `results/done/orphaned` verschoben statt alle fünf Minuten erneut Fehler zu erzeugen
- zugehörige veraltete Export-ZIPs werden beim Aufräumen ebenfalls entfernt
- manueller Suchlauf startet als Hintergrundauftrag und blockiert die App-Oberfläche nicht mehr bis zum Ende aller Portal- und Detailabfragen
- wiederholtes Antippen startet keinen zweiten parallelen Lauf desselben Suchprofils
- gespeicherte Dashboardfilter werden ohne 307-Redirect angewandt; die Startseite antwortet unter Home-Assistant-Ingress direkt mit HTTP 200
- Add-on-Version auf 0.14.8 erhöht

## 0.14.7

- fehlerhaften Home-Assistant-Optionsnamen `github_b64_imae_max_size` korrigiert, der das Update auf 0.14.6 blockierte
- veralteten GitHub-Base64-Bildtest aus dem Bootstrap und aus dem produktiven Lauf entfernt
- Base64-Testmodul und seine Export-Routen gelöscht
- KI-Bilder werden ausschließlich über das normale größenoptimierte Analysepaket übertragen
- bestehende Base64-Optionsnamen bleiben vorübergehend nur zur Home-Assistant-Updatekompatibilität erhalten und werden nicht mehr verwendet
- Add-on-Version auf 0.14.7 erhöht

## 0.14.6

- eine vorhandene alte KI-Analyse setzt einen neu gestarteten Analyselauf nicht mehr fälschlich auf „Analyse importiert“ zurück
- Frischeprüfung vergleicht jüngsten Export, Importzeitpunkt und den Analysezeitpunkt der Ergebnisdatei
- während ein neues Ergebnis aussteht, wird die bisherige Bewertung eindeutig als „Vorherige KI-Bewertung“ gekennzeichnet
- Verarbeitungsstatus zeigt den alten Analysezeitpunkt und den Zeitpunkt des neuen Exports getrennt an
- die alte Bewertung bleibt bis zum Rückimport als Vergleich sichtbar und wird danach automatisch ersetzt
- Dashboard zählt veraltete Analysen mit neuem Export als wartend statt abgeschlossen
- Add-on-Version auf 0.14.6 erhöht

## 0.14.5

- automatische Bestandsbereinigung beim und nach dem Add-on-Start vollständig entfernt
- Bild-Deduplizierung läuft nach abgeschlossenem Medienimport oder manuell
- KI-Export verwendet den bereits bereinigten und sortierten Bildbestand
- Add-on-Version auf 0.14.5 erhöht

Ältere Versionshinweise bleiben über die Git-Historie des Repositorys nachvollziehbar.
