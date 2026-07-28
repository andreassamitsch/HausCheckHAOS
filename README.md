# HausCheck HAOS Add-on

Lokaler Home-Assistant/HAOS-Dienst für Immobiliensuche, Hausakten, Dokumente, Medien und KI-gestützte Bewertung.

## Kernfunktionen

- Suchprofile für Willhaben, ImmobilienScout24 und Peisser
- Kandidaten prüfen, importieren, ablehnen und später wiederherstellen
- Hausakten aus Portal-Inseraten anlegen und aktualisieren
- Hausakten aus heruntergeladenen E-Mails (`.eml`), PDFs und Bildern anlegen
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

## Hausakt aus E-Mails anlegen

1. In Gmail jede Nachricht öffnen und über **⋮ → Nachricht herunterladen** als `.eml` speichern.
2. In HausCheck oben **+** und danach **E-Mails, PDFs und Bilder** wählen.
3. Mehrere `.eml`-Dateien gemeinsam hochladen. Direkte PDF- und Bilddateien können ergänzt werden.
4. Erkannte Objektdaten, Dokumenttypen und Widersprüche in der Vorschau prüfen.
5. **Hausakt als Entwurf anlegen** wählen. Original-E-Mails, PDFs, Bilder und Feldherkunft werden archiviert; optional startet danach die bestehende KI-Pipeline.

Der Import legt vor der Bestätigung keine Hausakte an. Allgemeine Broschüren wie Kaufnebenkosten-Informationen werden archiviert, erzeugen aber keine objektspezifischen Eckdaten.

## Datenablage

Persistente Daten liegen unter:

```text
/share/hauscheck
```

Jede Hausakte erhält einen eigenen Projektordner mit HTML, Bildern, PDFs, Original-E-Mails, Exporten und Analyseergebnissen.
