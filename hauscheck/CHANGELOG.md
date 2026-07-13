# Changelog

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
