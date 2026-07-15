# Changelog

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

## 0.12.0

- Oberfläche konsequent mobile-first und für schmale Smartphone-Displays neu aufgebaut
- Karten, Aktionsleisten, Formulare, Fakten und Navigation passen sich stufenweise an Tablet und Desktop an
- Kopfbereich einer Hausakte zeigt im Bild nur Ort, Preis, Wohnfläche, Grundstück und HWB
- langer Inseratstitel steht getrennt und gut lesbar unter dem Titelbild
- Antippen des Titelbilds öffnet eine In-App-Galerie statt einen direkten Medienlink
- neue Lightbox mit Vor/Zurück, Schließen, Mausrad-Zoom, Schaltflächen-Zoom und Zwei-Finger-Zoom
- dadurch keine Navigation mehr auf den unter Home-Assistant-Ingress problematischen direkten Bildlink
- Bilderbereich der Hausakte ist auf Smartphones zweispaltig
- beim Import hat das von Willhaben gelieferte Titelbild Vorrang, solange kein Bild manuell gewählt wurde
- manuell ausgewähltes Titelbild überschreibt weiterhin die automatische Auswahl
- kompakte, standardmäßig eingeklappte Sortier- und Filterfunktion für Importzeitpunkt, Bewertung, Ort, Preis, HWB, Wohnfläche und Grundstück ergänzt
- nicht importierte Suchkandidaten werden auf der Hauptseite nur noch als dezenter Link mit Zähler angezeigt
- Ablehnen-Symbol in Hauskarten rötlich gestaltet und auf dieselbe Höhe wie „Hausakte öffnen“ gebracht
- sichtbare Aktionen für Aktualisieren, Zusammenlegen, Titelbild und Bearbeiten bleiben in der mobilen Hausakte erreichbar
- eigener automatischer Mobil-UI-Test für Filter, Titelbildpriorität, Lightbox, Galerie und manuelle Bildauswahl ergänzt
- Add-on-Version auf 0.12.0 erhöht

## 0.11.1

- interne Links, Formulare und Medienpfade für Home-Assistant-Ingress korrigiert
- 404-Fehler bei „Hausakte anlegen“ für nicht importierte Kandidaten behoben
- Navigation zu Suche, Einstellungen, Ablehnungsarchiv, Zusammenlegen, Titelbild und Bearbeiten abgesichert
- alle Hauptseiten lösen relative Pfade jetzt automatisch auf den aktuellen Ingress-Basispfad auf
- echte Seitenaktualisierung über ein Refresh-Symbol im Kopf jeder Seite ergänzt
- die fachliche Aktualisierung einer Hausakte heißt zur klaren Unterscheidung jetzt „Inserat neu einlesen“
- automatischer Link-Audit prüft interne Links, Formulare und Medienpfade unter simuliertem Home-Assistant-Ingress
- Add-on-Version auf 0.11.1 erhöht

## 0.11.0

- Oberfläche vollständig neu strukturiert und visuell vereinheitlicht
- neue Design-Tokens, konsistente Abstände, Karten, Schaltflächen, Formulare und Statusdarstellungen
- responsive Desktop- und Mobilansicht mit eigener mobiler Hauptnavigation
- Hausakten stehen auf der Startseite klar im Mittelpunkt
- nicht importierte Suchkandidaten werden auf der Hauptübersicht als direkter Listenlink angezeigt
- zentrale Aktionsleiste in jeder Hausakte mit `Aktualisieren`, `Zusammenlegen`, `Titelbild` und `Bearbeiten`
- Zusammenführen ist jetzt als deutlich sichtbare eigene Seite umgesetzt
- Auswahl der zweiten Hausakte erfolgt mit Bild, Titel, Lage und Quellenanzahl
- Titelbildauswahl aus der Galerie auf eine eigene, aufgeräumte Seite verschoben
- normale Bildergalerie enthält keine störenden Vorschaubild-Schaltflächen mehr
- neue Aktualisieren-Funktion liest alle zugeordneten Makler-Inserate erneut ein
- beim Aktualisieren werden Stammdaten, Quellen, Feldnachweise, Bilder, PDFs und Kandidatendaten erneuert
- bei erkannten Änderungen oder neuen Medien wird automatisch eine neue KI-Analyse angestoßen
- Zeitpunkt und Zusammenfassung der letzten Aktualisierung werden in der Hausakte angezeigt
- Suchprofile können jetzt vollständig bearbeitet werden, einschließlich Regionen, areaIds, Such-URL, Preis-, Flächen-, HWB- und Automatikfiltern
- Add-on-Version auf 0.11.0 erhöht

## 0.10.0

- zwei Hausakten können zusammengeführt werden, wenn dasselbe Objekt von mehreren Maklern inseriert ist
- die aktuell geöffnete Hausakte bleibt bestehen; die ausgewählte zweite Hausakte wird eingegliedert
- Inseratsquellen, Maklerbeschreibungen, Feldnachweise, Bilder, PDFs und Kandidatenzuordnungen werden übernommen
- fehlende Stammdaten der Hauptakte werden aus der zweiten Hausakte ergänzt, vorhandene Hauptwerte bleiben bestehen
- doppelte Medien werden über Datei-Hash oder Original-URL erkannt und entfernt
- frühere KI-Analysen der zweiten Hausakte werden als Archivdateien erhalten
- Zusammenführungen werden mit Quelle, Medienanzahl, Duplikaten und Zeitpunkt protokolliert
- nach dem Zusammenführen wird automatisch ein neues kombiniertes Analysepaket nach GitHub exportiert
- Bildauswahl für Analysepakete wird auf mehrere Maklerquellen verteilt, damit nicht nur Bilder eines Inserats berücksichtigt werden
- jedes geladene Galeriebild kann als Vorschaubild der Hausakte ausgewählt werden
- das gewählte Vorschaubild wird in der Übersicht und in der Galerie zuerst angezeigt
- automatische Vorschaubildauswahl kann wieder aktiviert werden
- Add-on-Version auf 0.10.0 erhöht

## 0.9.0

- Preisverlauf je Kandidat ergänzt
- Preisänderungen werden mit altem Wert, neuem Wert, Prozentänderung und Zeitpunkt hervorgehoben
- relevante Änderungen an Titel, Preis, Wohnfläche, Grundstück, HWB und Vorschaubild werden protokolliert
- neue Kandidatenstatus `changed`, `offline` und `reactivated`
- ein Inserat gilt erst nach zwei erfolgreichen Suchläufen ohne erneuten Fund als offline
- Null-Treffer-Läufe setzen keine Inserate vorschnell auf offline
- wieder erschienene Inserate werden als „wieder online“ markiert
- bei Änderungen an bereits importierten Objekten wird auf der Hauskarte eine erneute Analyse empfohlen
- die Empfehlung wird nach erfolgreichem Analyseimport automatisch zurückgesetzt
- geänderte und wieder aktive Kandidaten können in der Vollautomatik erneut berücksichtigt werden
- Suchprofile können inklusive Kandidaten- und Preisverlauf gelöscht werden; bestehende Hausakten bleiben erhalten
- neues Suchprofil wird unter `Einstellungen → Suchprofile` oben über einen Plus-Button angelegt
- Add-on-Version auf 0.9.0 erhöht

## 0.8.0

- HWB-Werte werden mit Punkt oder Komma als Dezimaltrennzeichen gelesen
- `306.1` und `306,1` ergeben beide korrekt `306,1`
- strukturierte Werte aus Tabellen, Definitionslisten und Wertelisten haben Vorrang vor allgemeinen Seitentexten
- fehlerhafte Nebenfundstellen können dadurch einen klaren Listenwert nicht mehr überschreiben
- PDF- und manuelle Dezimalwerte werden ebenfalls ohne Verlust der Nachkommastelle verarbeitet
- Startseite konsequent auf aktive Hausakten reduziert
- Suche wird direkt über eine Lupen-Schaltfläche gestartet
- Suchprofile und Automatikparameter befinden sich unter `Einstellungen → Suchprofile`
- Hausakten können in der Übersicht über ein Mülleimer-Symbol abgelehnt werden
- abgelehnte Hausakten verschwinden aus der Hauptübersicht und bleiben im Ablehnungsarchiv erhalten
- eigene Seite für abgelehnte Hausakten und Kandidaten ergänzt
- Wiederherstellen und endgültiges Löschen sind im Ablehnungsarchiv möglich
- abgelehnte Kandidaten bleiben auch nach späteren Suchläufen abgelehnt
- Add-on-Version auf 0.8.0 erhöht

## 0.7.1

- alle sichtbaren Zeitangaben auf `Europe/Vienna` umgestellt
- Zeitformat auf `TT.MM.JJJJ HH:MM` verkürzt
- neue Option `display_timezone`
- KI-Score ersetzt nach erfolgreicher Analyse die regelbasierte Hauptbewertung
- regelbasierte Bewertung bleibt als einklappbare Daten-Vorprüfung sichtbar
- Analyseformat um Kaufpreiseinschätzung erweitert
- neuer fairer Preisbereich, erstes Angebot, Zielpreis und empfohlene Obergrenze
- Investitionsbedarf wird zusätzlich in einzelne Maßnahmen mit Priorität, Kostenspanne, Sicherheit und Grundlage aufgeteilt
- grobe Projektkostenspanne aus Zielkaufpreis und Investitionen ergänzt
- Kaufnebenkosten und Finanzierung werden nur einbezogen, wenn dies ausdrücklich dokumentiert ist
- Add-on-Version auf 0.7.1 erhöht

## 0.7.0

- zeitgesteuerten Willhaben-Such-Scheduler ergänzt
- Suchprofile können pausiert, manuell, halbautomatisch oder vollautomatisch betrieben werden
- halbautomatisch: Suche läuft im Hintergrund, Kandidaten werden manuell importiert
- vollautomatisch: passende Kandidaten werden als Hausakte angelegt, Medien geladen und zur ChatGPT-Analyse exportiert
- Auto-Import verwendet nur Kandidaten mit Status `new` und konfigurierbarem Mindestscore
- Anzahl automatischer Importe je Suchlauf ist begrenzt
- bestehende Inserate werden über Portal-ID und Quell-URL gegen Doppelimporte geschützt
- Suchprofile zeigen Laufstatus, Fehler, Intervall, Mindestscore und Auto-Import-Limit
- neue globale Optionen `search_automation_enabled` und `search_scheduler_poll_seconds`
- Add-on-Version auf 0.7.0 erhöht

## 0.6.0

- normale Hausaktenansicht auf den produktiven Workflow reduziert
- frühere GitHub-, Base64-, Gmail- und manuelle Analysepaket-Schaltflächen aus der normalen Oberfläche entfernt
- neue zentrale Aktion `Analyse erneut anstoßen`
- technische Medien-, Quellen- und Pipeline-Details in einen eingeklappten Diagnosebereich verschoben
- persistentes Pipeline-Statusmodell mit Ereignishistorie ergänzt
- sichtbare Schritte: Inserat erfasst, Medien geladen, zur Analyse bereitgestellt, ChatGPT-Analyse importiert
- Dashboard zeigt wartende, abgeschlossene und fehlerhafte Verarbeitungsvorgänge
- Suchprofil-Datenbank für Automatikmodus, Intervall, areaIds und maximale Trefferzahl erweitert
- Kandidaten-Datenbank um Provider, externe Inserat-ID, kanonische URL, Inhalts-Hash, Änderungszeitpunkt, Änderungszähler, Entscheidung und Rohdaten ergänzt
- Suchprofil- und Kandidatenansicht für die kommende automatische Willhaben-Suche vorbereitet
- Add-on-Version auf 0.6.0 erhöht

## 0.5.15

- Base64-Chunks werden für Connector-Lesezugriffe in kurze Zeilen umgebrochen
- neue Option `github_b64_line_length`

## 0.5.14

- GitHub Base64-Bildtest ergänzt
- neue Schaltfläche `Base64-Bildtest exportieren` in der Hausakte im Bereich GitHub AI Exchange
- exportiert ein echtes lokal geladenes Hausbild als Base64-Text-Chunks nach GitHub
- Testpfad: `ai_exchange/tests/base64/<house_id>/`
- schreibt `manifest.json`, `prompt.md`, Bild-Metadaten und `part_*.txt` Chunks
- Bilder werden nicht stark verkleinert: Standard `max_size=1800`, `quality=90`; vorhandene JPGs innerhalb der Grenze werden original übernommen
- neue Optionen `github_b64_test_path`, `github_b64_image_limit`, `github_b64_image_max_size`, `github_b64_image_quality`, `github_b64_chunk_size`

## 0.5.13

- Gmail Export von ZIP-Anhang auf lesbares Mail-Paket umgestellt
- Mailbody enthält jetzt `HAUSCHECK_MAIL_PACKAGE_V2` mit README_PROMPT, listing.json, evidence.json, current_score.json, import_schema.json und image_manifest.json
- Bilder werden optional einzeln als Bildanhänge mitgeschickt
- ZIP-Anhang ist standardmäßig deaktiviert, weil der ChatGPT-Gmail-Connector ZIP-Anhänge nicht zuverlässig lesen kann
- neue Optionen `gmail_inline_package`, `gmail_attach_images`, `gmail_image_limit`, `gmail_send_zip_attachment`
- ChatGPT-Automation wurde auf den neuen Mailbody-Workflow aktualisiert

## 0.5.12

- Gmail AI Exchange ergänzt
- Analysepakete können nach Inserat-Import automatisch per Gmail/SMTP versendet werden
- fertige KI-Analysen können per Gmail/IMAP automatisch aus ungelesenen `HAUSCHECK_RESULT <house_id>`-Mails importiert werden
- Rückgabe kann als JSON-Anhang oder als reiner JSON-Mailbody erfolgen
- neue Add-on-Optionen für Gmail SMTP, IMAP, Benutzer, App-Passwort, Empfänger und Importintervall
- bestehender GitHub Exchange bleibt als Fallback erhalten
- ChatGPT-Automation wurde auf Gmail-Exchange umgestellt

## 0.5.11

- automatischer GitHub-Rückimport für fertige KI-Analysen ergänzt
- neue Add-on-Optionen `github_auto_import_results` und `github_auto_import_interval_minutes`
- Standard: HausCheck prüft alle 5 Minuten `ai_exchange/results/pending`
- gefundene `hauscheck_analysis.json` werden automatisch in die passende Hausakte importiert
- erfolgreiche Ergebnisse werden wie bisher nach `results/done` archiviert und pending-Dateien/Export-ZIPs aufgeräumt
- Auto-Import läuft im Hintergrund und protokolliert Import/Fehler im Add-on-Log

## 0.5.10

- automatischer GitHub-AI-Export nach Inserat-Import ergänzt
- neue Add-on-Option `github_auto_export_on_import`
- Standard: Nach erfolgreichem Import und Medien-Download wird automatisch `<house_id>.zip` nach `ai_exchange/exports/pending` geschrieben
- Fehler beim Auto-Export blockieren den Hausimport nicht; Details stehen im Add-on-Log
- Import-Route über Patch-Modul stabilisiert, damit Direktimport und Kandidatenimport denselben Auto-Export nutzen

## 0.5.8

- GitHub AI Exchange ergänzt
- neue Add-on-Optionen für GitHub-Repo, Branch, Token und Austauschpfade
- Hausakte enthält jetzt einen Bereich „GitHub AI Exchange"
- Button „Analysepaket nach GitHub exportieren“ lädt das ZIP nach `ai_exchange/exports/pending/<house_id>.zip`
- Button „GitHub-Ergebnisse importieren“ liest `ai_exchange/results/pending/.../hauscheck_analysis.json`
- importierte Ergebnisse werden lokal in der Hausakte gespeichert
- nach erfolgreichem Import wird das JSON nach `results/done/<house_id>/...json` archiviert
- exportierte ZIPs und pending-Ergebnisse werden nach erfolgreichem Import aus GitHub aufgeräumt, wenn `github_cleanup_after_import` aktiv ist
