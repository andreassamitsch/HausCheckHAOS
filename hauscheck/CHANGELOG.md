# Changelog

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
