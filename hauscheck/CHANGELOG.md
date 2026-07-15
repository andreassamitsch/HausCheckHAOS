# Changelog

## 0.15.0

- gewachsene Such-Wrapper durch einen eindeutigen finalen Suchablauf ersetzt
- Portal- und Detailseiten werden pro Lauf nur einmal geladen; kurz aufeinanderfolgende Abrufe verwenden einen begrenzten Arbeitsspeicher-Cache
- bereits geparste unveränderte Detailseiten werden nicht erneut geparst
- Peisser-Detailpakete und Parserergebnisse werden zwischen Suche und Vorab-Deduplizierung wiederverwendet
- starke eindeutige Faktenübereinstimmungen werden vor Bilddownloads geprüft; nur uneindeutige Fälle benötigen die visuelle Cross-Portal-Prüfung
- ohne vorhandene Hausakten werden keine nutzlosen Vorschaubilder zur Duplikatsuche geladen
- Medienbereinigung läuft nach einem tatsächlichen neuen Bilddownload genau einmal und in einem Worker-Thread
- Preis- oder Textänderungen ohne neue Bilder starten keine vollständige Galeriebereinigung mehr
- automatische Suchprofile erhalten zwischen den Läufen eine kurze Schonpause; alle Profile werden weiterhin vollständig ausgeführt
- fehlerhafte Willhaben-Parameter wie `areaId=['8551']` werden beim Start und unmittelbar vor dem Abruf zu `areaId=8551` repariert
- temporäre Portalfehler der HTTP-500-Klasse werden einmal kontrolliert wiederholt
- Suchprotokoll zeigt Laufzeit, Netzwerkabrufe, Cachetreffer sowie vermiedene Bild- und Bereinigungsläufe
- Live-Prüfung erfolgreich mit Willhaben, ImmobilienScout24 und Peisser Immobilien
- Add-on-Version auf 0.15.0 erhöht

## 0.14.9

- jedes neue Analysepaket erhält eine eindeutige `analysis_request_id`
- Rückgabeformat und Analyseprompt verlangen die unveränderte Auftragskennung im Ergebnis
- alte Ergebnisse derselben Hausakte können einen neueren Export nicht mehr fälschlich abschließen
- Übergangsprüfung weist Legacy-Ergebnisse zurück, deren Analysezeitpunkt vor dem jüngsten Export liegt
- veraltete Ergebnisse werden nach `results/done/stale` archiviert und aus `results/pending` entfernt
- das aktuelle Export-ZIP bleibt bei einem veralteten Ergebnis erhalten und wird weiter zur Analyse angeboten
- der GitHub-Artifact-Workflow behandelt eine leere Pending-Warteschlange als normalen erfolgreichen Zustand
- bei leerer Warteschlange wird `latest_artifact.json` auf `status: empty` gesetzt, damit kein alter Artifact-Zeiger erneut verarbeitet wird
- Add-on-Version auf 0.14.9 erhöht

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

Ältere Versionshinweise bleiben über die Git-Historie des Repositorys nachvollziehbar.
