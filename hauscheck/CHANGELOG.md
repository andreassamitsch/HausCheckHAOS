# Changelog

## 0.17.2

- Home-Assistant-App-Store kann direkt aus HausCheck unter `Einstellungen → HausCheck-Updates` neu geladen werden
- neue Releases werden damit sichtbar, ohne auf den zeitgesteuerten Repository-Check zu warten
- Supervisor-Zugriff ist ausschließlich für den offiziellen Endpunkt `/store/reload` vorgesehen
- verbindlicher Release-Guard prüft Versionsnummer, Changelog, Syntax, Tests und den veröffentlichten `main`-Stand
- Release-Ablauf und Ursache des wiederholten scheinbaren Updatefehlers dauerhaft im Repository dokumentiert
- Add-on-Version auf 0.17.2 erhöht

## 0.17.1

- `Postfach jetzt prüfen` verwendet unter Home-Assistant-Ingress wieder den korrekten POST-Endpunkt
- E-Mail-Karten öffnen unabhängig von einem abschließenden Schrägstrich die richtige Nachricht
- `Zuordnen`, `Ignorieren` und die Rückkehr zum Posteingang behalten Ingress-Präfix und Nachrichten-ID bei
- Regressionstests für alle Posteingangs- und Detailaktionen ergänzt
- Add-on-Version auf 0.17.1 erhöht

## 0.17.0

- eigener IMAP-Posteingang für weitergeleitete Hausunterlagen ergänzt
- neue E-Mails werden lokal als Original-EML archiviert und mit Anhängen, Bildern und erkannten Objektdaten aufbereitet
- ausdrücklich keine automatische Zuordnung und keine automatische Hausakte: jede E-Mail wartet im Bereich `E-Mail-Posteingang` auf eine manuelle Entscheidung
- E-Mail kann einer bestehenden Hausakte zugeordnet, als neue Hausakte angelegt oder ignoriert werden
- nach der manuellen Zuordnung können Dokumente, Bilder, Feldnachweise und die bestehende KI-Analyse übernommen beziehungsweise aktualisiert werden
- doppelte Nachrichten werden anhand von Message-ID beziehungsweise Inhalts-Hash erkannt
- IMAP-Server, Postfach, Passwort, Ordner, Abrufintervall und Gelesen-Markierung sind in den Add-on-Einstellungen konfigurierbar
- Add-on-Version auf 0.17.0 erhöht

## 0.16.1

- Android-/Home-Assistant-Dateidialog für den manuellen Import nicht mehr auf unzuverlässige MIME-Filter beschränkt
- Gmail-E-Mails werden als `.eml` auch bei `application/octet-stream`, `text/plain`, fehlender Dateiendung oder generischem Android-Dateityp erkannt
- Dateiinhalt wird vor dem Import sicher geprüft; nicht unterstützte Dateien bleiben abgelehnt
- mehrere E-Mails, PDFs und Bilder können weiterhin gemeinsam importiert werden
- Regressionstests für EML-, PDF-, JPEG- und PNG-Erkennung ergänzt
- Add-on-Version auf 0.16.1 erhöht

## 0.16.0

- Hausakten können aus mehreren heruntergeladenen Gmail-Nachrichten (`.eml`), PDFs und Bildern angelegt werden
- E-Mail-Text, PDF-Anhänge und eingebettete Bilder werden automatisch extrahiert
- erkannte Objektdaten werden vor dem Speichern mit Feldherkunft und Konflikthinweisen angezeigt
- Original-E-Mails, Dokumente und Bilder werden in der Hausakte archiviert
- doppelte Anhänge und Bilder werden anhand ihres Inhalts erkannt
- bestehende KI-Analyse kann nach dem Import automatisch gestartet werden
- Add-on-Version auf 0.16.0 erhöht

## 0.15.1

- automatische Suchläufe erzeugen für inhaltlich identische Analysepakete keine neue Auftragskennung mehr
- fachlicher Paket-Fingerprint ignoriert Zeitstempel, wechselnde Parser-Textausschnitte, Trackingparameter und ZIP-Metadaten
- ein bereits hochgeladener oder bereits importierter identischer Auftrag wird nicht erneut nach GitHub übertragen
- eine laufende Analyse wird durch spätere automatische Such- oder Quellenaktualisierungen nicht mehr ersetzt
- echte Änderungen während eines laufenden Auftrags werden vorgemerkt und nach dem Ergebnis zu höchstens einem Folgeauftrag zusammengefasst
- Feldnachweise werden semantisch verglichen; wechselnde Snippets und Whitespace gelten nicht mehr als neue Information
- Bild-URL-Parameter gelten nicht mehr als neues Bild, sofern der stabile Bildinhalt beziehungsweise die kanonische URL gleich bleibt
- der manuelle Button `Analyse erneut anstoßen` erzwingt weiterhin bewusst einen neuen Auftrag
- Regressionstest des nächtlichen Automatismus vollständig erfolgreich
- Add-on-Version auf 0.15.1 erhöht

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
- manueller Suchlauf startet als Hintergrundauftrag und blockiert die Oberfläche nicht mehr bis zum Ende aller Portal- und Detailabfragen
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
