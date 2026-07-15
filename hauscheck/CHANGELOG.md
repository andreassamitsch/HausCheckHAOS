# Changelog

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
- Regressionstest prüft Start, KI-Export, Import und manuellen Auslöser getrennt
- Add-on-Version auf 0.14.5 erhöht

## 0.14.4

- blockierende vollständige Bildbereinigung aus dem Add-on-Start entfernt
- Home-Assistant-Ingress und HTTP-Server werden sofort freigegeben
- bestehende Hausakten werden erst nach dem Start gedrosselt im Hintergrund bereinigt
- jede Hausakte wird in einem separaten Worker-Schritt verarbeitet, damit die Oberfläche erreichbar bleibt
- manueller Bereinigungsbutton und automatische Bereinigung nach neuen Downloads bleiben erhalten
- Starttest mit einer vorbereiteten Galerie aus 70 Bildern ergänzt
- Add-on-Version auf 0.14.4 erhöht

## 0.14.3

- Bildbereinigung erkennt nun auch redundante Aufnahmen desselben Raums mit leicht versetzter Kameraposition
- tolerantere Szenenerkennung wird ausschließlich zwischen verschiedenen Inseratquellen angewandt
- unterschiedliche Perspektiven innerhalb derselben Portalgalerie bleiben erhalten
- überflüssige Bilddatensätze und lokale Dateien werden physisch entfernt
- die mobile Smartphone-Galerie verwendet jetzt ebenfalls die gespeicherte Portalreihenfolge
- sichtbare Aktion `Doppelte Bilder bereinigen` in jeder Hausakte ergänzt
- vorhandene Bilder werden wegen der neuen Fingerprint-Version beim ersten Start vollständig neu geprüft
- Add-on-Version auf 0.14.3 erhöht

## 0.14.2

- portalübergreifende Bild-Deduplizierung für identische, neu komprimierte, verkleinerte und leicht zugeschnittene Fotos verbessert
- überflüssige Bilddatensätze und zugehörige lokale Dateien werden tatsächlich entfernt
- ähnliche, aber unterschiedliche Perspektiven bleiben erhalten
- bestehende Hausakten werden beim ersten Start einmalig auf überflüssige Bilder geprüft und bereinigt
- Galerien folgen der Reihenfolge der vollständigsten Inseratquelle; zusätzliche Bilder anderer Anbieter werden danach in deren Portalreihenfolge ergänzt
- ein manuell gewähltes Titelbild verändert die Galeriereihenfolge nicht mehr
- KI-Export von bisher 12 auf bis zu 80 eindeutige Bilder erweitert
- bei sehr großen Galerien wird gleichmäßig über die vollständige Galerie ausgewählt, damit auch spätere Innenansichten enthalten sind
- `image_selection.json` und `image_coverage` dokumentieren Bildauswahl und geprüfte Innen-, Außen-, Technik- und Planansichten
- Add-on-Version auf 0.14.2 erhöht

## 0.14.1

- reale Peisser-Cross-Portal-Zuordnung für bestehende Hausakten korrigiert
- starke Übereinstimmungen aus Ort, Wohnfläche, Grundstück, Zimmern, Preis, HWB, Heizung und Baujahr können auch ohne alte Portalbilder oder ähnliche Maklertitel sicher zusammengeführt werden
- Peisser-Heizungsart wird aus konkreten Heizungsbegriffen im Beschreibungstext erkannt
- Peisser-Kandidaten behalten nach dem Suchlauf korrekte Portal-, Exposé- und kanonische URL-Metadaten
- bestehende falsch zugeordnete Peisser-Profile werden beim Start repariert
- Add-on-Version auf 0.14.1 erhöht

## 0.14.0

- Peisser Immobilien als zusätzliche Portalquelle und Suchprofiltyp ergänzt
- Angebotsseiten 1 bis 10 werden geprüft; bei leerer oder wiederholter Seite wird automatisch beendet
- Titel mit `VERKAUFT` werden vor Import und Kandidatenanzeige ausgeschlossen
- Peisser-Grunddaten, Beschreibung, Energiekennzahlen und Galerie werden zu einem vollständigen Inserat zusammengesetzt
- lokale Filterung nach PLZ, Preis, Wohnfläche, Grundstück, Objektart und bestehenden HausCheck-Regeln ergänzt
- Peisser-Treffer laufen vor der Kandidatenanzeige durch die Cross-Portal-Deduplizierung
- Add-on-Version auf 0.14.0 erhöht

## 0.13.5

- sichere Deduplizierung wird vor Kandidatenanzeige und Import ausgeführt
- bekannte Inserate erscheinen nicht mehr irreführend als neue Kandidaten
- neue Maklerquellen, Beschreibungen, Feldnachweise und Medien werden direkt in bestehende Hausakten übernommen
- unveränderte bekannte Inserate lösen keine erneute KI-Analyse aus
- tatsächliche Daten-, Quellen- oder Medienänderungen starten automatisch eine neue Bewertung
- Add-on-Version auf 0.13.5 erhöht

## 0.13.4

- ImmobilienScout24-Suchabruf für abweichende Browser-, JavaScript-, JSON- und Unicode-Darstellungen gehärtet
- Portal-Sitzung wird vor dem Suchabruf aufgebaut und mehrere sichere Abrufvarianten werden versucht
- codierte Exposé-Links werden zuverlässig erkannt
- Bot-, Consent- oder JavaScript-Seiten liefern eine konkrete Diagnose statt irreführend `0 Ergebnisse`
- Add-on-Version auf 0.13.4 erhöht

## 0.13.3

- ImmobilienScout24-Parameter werden als ganze Zahlen ohne `.0` erzeugt und gespeichert
- tatsächlicher Suchlauf verwendet dieselben normalisierten URLs wie die sichtbare Vorschau
- Browser-Header für ImmobilienScout24-Suchabrufe ergänzt
- Add-on-Version auf 0.13.3 erhöht

## 0.13.2

- wiederholte Verzehnfachung von Wohn- und Grundstücksflächen beim Speichern von Suchprofilen behoben
- bereits beschädigte ImmobilienScout24-Profile werden beim Start automatisch repariert
- Dezimalwerte bleiben bei wiederholtem Speichern stabil
- Add-on-Version auf 0.13.2 erhöht

## 0.13.1

- ImmobilienScout24-Such-URLs werden dynamisch aus PLZ, Preis-, Wohnflächen- und Grundstücksfiltern erstellt
- mehrere PLZ erzeugen automatisch mehrere getrennte Portalabfragen
- Such-URLs werden beim Bearbeiten eines Profils neu berechnet
- eigene Spezial-URLs bleiben über einen eindeutigen benutzerdefinierten Modus erhalten
- Add-on-Version auf 0.13.1 erhöht

## 0.13.0

- ImmobilienScout24 Österreich als Portalquelle und Suchprofiltyp ergänzt
- strukturierter Exposé-Parser für Preis, Wohnfläche, Grundstück, Zimmer, Lage, Baujahr, Heizung, HWB, fGEE und Galerie
- hochauflösende ImmobilienScout24-Galeriebilder werden mit passenden Portal-Headern geladen
- Cross-Portal-Deduplizierung über Portal-ID, kanonische URL, Fakten und Wahrnehmungs-Fingerprints ergänzt
- weitere Maklerquellen desselben Objekts werden derselben Hausakte zugeordnet
- Add-on-Version auf 0.13.0 erhöht

## 0.12.7

- `PDF öffnen` bleibt im authentifizierten Home-Assistant-Ingress und öffnet nicht mehr in einem unautorisierten externen Fenster
- separater PDF-Download ergänzt
- Add-on-Version auf 0.12.7 erhöht

## 0.12.6

- Exposé-PDFs können aus einer Hausakte entfernt werden
- Upload, erneutes Auslesen, Adressentscheidung und Löschen stoßen eine neue KI-Bewertung an
- größenbewusster PDF-Export mit extrahiertem Text, Dokumentmanifest und optionalem Original-PDF ergänzt
- große PDFs werden nicht nur gezippt, sondern kompakt als Text und vorhandene Bilder an die KI übergeben
- Add-on-Version auf 0.12.6 erhöht

Ältere Versionshinweise bleiben über die Git-Historie des Repositorys nachvollziehbar.
