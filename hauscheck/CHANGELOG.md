# Changelog

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
- keine wiederkehrende oder verzögerte Prüfung sämtlicher bestehender Hausakten mehr
- Bild-Deduplizierung läuft genau einmal nach abgeschlossenem Medienimport oder Aktualisieren einer Hausakte
- manuelle Aktion `Doppelte Bilder bereinigen` bleibt für bestehende Galerien verfügbar
- KI-Export verwendet den bereits bereinigten und sortierten Bildbestand ohne erneuten Vergleich
- Add-on-Version auf 0.14.5 erhöht

## 0.14.4

- blockierende vollständige Bildbereinigung aus dem Add-on-Start entfernt
- Home-Assistant-Ingress und HTTP-Server werden sofort freigegeben
- Add-on-Version auf 0.14.4 erhöht

## 0.14.3

- Bildbereinigung erkennt redundante Aufnahmen desselben Raums aus verschiedenen Inseratquellen
- mobile Galerie verwendet die gespeicherte Portalreihenfolge
- manuelle Aktion `Doppelte Bilder bereinigen` ergänzt
- Add-on-Version auf 0.14.3 erhöht

## 0.14.2

- portalübergreifende Bild-Deduplizierung verbessert
- Galerien folgen der Portalreihenfolge
- KI-Export auf bis zu 80 eindeutige Bilder erweitert
- Add-on-Version auf 0.14.2 erhöht

Ältere Versionshinweise bleiben über die Git-Historie des Repositorys nachvollziehbar.
