# HausCheck HAOS Add-on

Lokaler Home-Assistant/HAOS Dienst für Immobilienrecherche und Medien-Download.

## Ziel

HausCheck soll die Haussuche leichter machen:

- Immobilienportale durchsuchen
- echte Inserat-Direktlinks sammeln
- Inseratdaten sichern
- sichtbare Bild-URLs erkennen
- Bilder lokal nach Home Assistant herunterladen
- manuelle Bilder/PDFs ergänzen
- Analysebriefing für spätere KI-/ChatGPT-Bewertung erzeugen

## Installation in Home Assistant

1. In Home Assistant öffnen:
   **Einstellungen → Add-ons → Add-on Store**
2. Rechts oben auf **⋮ → Repositories**
3. Dieses Repository hinzufügen:

```text
https://github.com/andreassamitsch/HausCheckHAOS
```

4. Add-on Store neu laden.
5. **HausCheck Pro** installieren und starten.
6. Weboberfläche öffnen:

```text
http://homeassistant.local:8088
```

oder über die IP deines Home Assistant:

```text
http://<HA-IP>:8088
```

## Aktueller MVP-Umfang

- Weboberfläche auf Port `8088`
- Willhaben-Suche mit nativen Filterparametern für Deutschlandsberg
- Direktlink-Import
- HTML speichern
- sichtbare Bild-URLs aus HTML/JSON erkennen
- Bilder lokal nach `/share/hauscheck/projects/.../images` herunterladen
- manuelle Bilder/PDFs hochladen
- Analysebriefing als Markdown erzeugen

## Noch nicht enthalten

- keine automatische KI-Bewertung
- keine vollständige Browser-/Galerie-Automation
- keine HORA-/Katasterprüfung
- keine täglichen Jobs
- noch keine weiteren Portale außer erster Willhaben-Logik

## Datenablage

Persistente Daten liegen unter:

```text
/share/hauscheck
```

## Nächste Ausbaustufen

1. tägliche Suche/Scheduler
2. weitere Portale: ImmobilienScout24, Immowelt, RE/MAX, Raiffeisen, sREAL, Peisser, Immobilien.net
3. Playwright/Chromium-Galerie-Automation als Fallback für blockierte Bild-URLs
4. OpenAI-/ChatGPT-Bewertung optional
5. Push-Benachrichtigung über Home Assistant Companion App
