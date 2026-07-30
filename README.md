# HausCheck HAOS Add-on

Lokaler Home-Assistant/HAOS-Dienst für Immobiliensuche, Hausakten, Dokumente, Medien und KI-gestützte Bewertung.

## Kernfunktionen

- Suchprofile für Willhaben, ImmobilienScout24 und Peisser
- Kandidaten prüfen, importieren, ablehnen und später wiederherstellen
- Hausakten aus Portal-Inseraten anlegen und aktualisieren
- eigener IMAP-Posteingang für weitergeleitete E-Mails mit ausschließlich manueller Zuordnung
- Hausakten alternativ aus heruntergeladenen E-Mails (`.eml`), PDFs und Bildern anlegen
- PDF-Anhänge und eingebettete E-Mail-Fotos automatisch übernehmen
- Grundbuch, Energieausweis, Flächenwidmung, Luftbild und allgemeine Unterlagen unterscheiden
- erkannte Daten mit Feldherkunft und Konflikthinweisen vor dem Speichern prüfen
- Bilder lokal sichern, Duplikate bereinigen und ein Titelbild wählen
- doppelte Makler-Inserate zu einer Hausakte zusammenlegen
- Analysepakete automatisch über den konfigurierten GitHub-Austausch bereitstellen und Ergebnisse zurückimportieren

## Installation in Home Assistant

1. **Einstellungen → Add-ons → Add-on Store** öffnen.
2. Rechts oben **⋮ → Repositories** wählen.
3. Dieses Repository hinzufügen:

```text
https://github.com/andreassamitsch/HausCheckHAOS
```

4. Add-on Store neu laden.
5. **HausCheck Pro** installieren und starten.
6. Die Weboberfläche über Home-Assistant-Ingress öffnen.

Der optionale direkte Port `8088` kann in den Add-on-Einstellungen freigegeben werden.

## E-Mail-Posteingang einrichten

Für den normalen Alltag empfiehlt sich ein eigenes Postfach wie `hauscheck@hauscheck.pro` bei einem Mailanbieter mit IMAP-Zugang. HausCheck Pro benötigt keinen öffentlich erreichbaren Mailserver und keine Portfreigabe. Das Add-on verbindet sich ausgehend per verschlüsseltem IMAP mit dem Postfach.

In den Add-on-Einstellungen eintragen:

```text
mail_inbox_enabled: true
mail_inbox_imap_host: IMAP-Server des Anbieters
mail_inbox_imap_port: 993
mail_inbox_username: hauscheck@hauscheck.pro
mail_inbox_password: Postfachpasswort
mail_inbox_folder: INBOX
mail_inbox_interval_minutes: 2
mail_inbox_mark_seen: true
```

Danach das Add-on neu starten. Unter **+ → E-Mail-Posteingang** können neue Nachrichten sofort geprüft werden.

### Ablauf

1. Eine Makler-E-Mail an `hauscheck@hauscheck.pro` weiterleiten.
2. HausCheck ruft die Nachricht samt PDF- und Bildanhängen ab und legt sie im lokalen Posteingang ab.
3. HausCheck führt ausdrücklich keine automatische Zuordnung durch.
4. Im Posteingang die E-Mail öffnen und entweder eine bestehende Hausakte auswählen, einen neuen Entwurf anlegen oder die Nachricht ignorieren.
5. Erst nach dieser Entscheidung werden E-Mail, Anhänge und Feldnachweise in die Hausakte übernommen; optional wird die KI-Analyse aktualisiert.

Doppelte E-Mails werden anhand der Message-ID beziehungsweise des Inhalts erkannt. Das Original bleibt als `.eml` lokal archiviert.

## Manueller Dateiimport als Alternative

1. In Gmail eine Nachricht über **⋮ → Nachricht herunterladen** als `.eml` speichern.
2. In HausCheck oben **+** und danach **E-Mails, PDFs und Bilder** wählen.
3. Mehrere `.eml`-Dateien gemeinsam hochladen. Direkte PDF- und Bilddateien können ergänzt werden.
4. Erkannte Objektdaten, Dokumenttypen und Widersprüche in der Vorschau prüfen.
5. **Hausakt als Entwurf anlegen** wählen.

Der Import legt vor der Bestätigung keine Hausakte an. Allgemeine Broschüren wie Kaufnebenkosten-Informationen werden archiviert, erzeugen aber keine objektspezifischen Eckdaten.

## Datenablage

Persistente Daten liegen unter:

```text
/share/hauscheck
```

Jede Hausakte erhält einen eigenen Projektordner mit HTML, Bildern, PDFs, Original-E-Mails, Exporten und Analyseergebnissen. Der noch nicht zugeordnete E-Mail-Posteingang liegt unter `/share/hauscheck/mail_inbox`.
