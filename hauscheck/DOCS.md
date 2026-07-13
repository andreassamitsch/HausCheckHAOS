# HausCheck Pro Add-on

## Aktueller Funktionsumfang v0.11.0

HausCheck verwaltet Immobilien als Hausakten, sucht passende Willhaben-Inserate, lädt Medien, übergibt Analysepakete über GitHub an ChatGPT und importiert die fertige KI-Bewertung automatisch zurück.

Neu in 0.11.0:

- vollständig überarbeitete responsive Oberfläche
- Hausakten als klare Hauptansicht
- sichtbare Aktionen zum Aktualisieren, Zusammenlegen, Titelbild wählen und Bearbeiten
- direkter Link zu allen noch nicht importierten Suchkandidaten
- vollständige Bearbeitung bestehender Suchprofile

## Navigation

Auf Mobilgeräten steht unten eine feste Navigation bereit:

```text
Hausakten · Suche · Abgelehnt · Einstellungen
```

Auf größeren Bildschirmen befinden sich die wichtigsten Aktionen im Seitenkopf beziehungsweise direkt in der jeweiligen Hausakte.

## Hausaktenübersicht

Die Startseite zeigt aktive Hausakten mit:

- ausgewähltem Titelbild
- Titel und Lage
- KI-Score beziehungsweise vorläufiger Datenbewertung
- Pipeline-Status
- Preis, Wohnfläche und Grundstück

Oberhalb der Hausakten erscheint ein direkter Listenlink:

```text
X nicht importierte Suchkandidaten
```

Dieser öffnet die Kandidatenliste zum Prüfen, Importieren oder Ablehnen.

## Hausakte aktualisieren

In jeder geöffneten Hausakte steht oben die Aktion **Aktualisieren**.

Der Ablauf:

```text
alle zugeordneten Makler-Inserate erneut laden
→ Inseratsdaten neu auslesen
→ Quellen und Feldnachweise aktualisieren
→ neue Bilder und PDFs ergänzen
→ Kandidatendaten aktualisieren
→ Änderungen zusammenfassen
→ bei relevanten Änderungen neue KI-Analyse starten
```

Die Hausakte zeigt danach Datum, Uhrzeit und Zusammenfassung der letzten Aktualisierung. Ist keine aktualisierbare HTTP-Quelle vorhanden, wird eine verständliche Fehlermeldung ausgegeben.

## Zwei Hausakten zusammenführen

Die Funktion ist direkt in der oberen Aktionsleiste jeder Hausakte sichtbar:

```text
Zusammenlegen
```

Auf der eigenen Auswahlseite werden alle anderen aktiven Hausakten mit Bild, Titel, Lage und Quellenanzahl angezeigt. Die aktuell geöffnete Hausakte bleibt die Hauptakte.

Übernommen werden:

- Inseratsquellen und Maklerbeschreibungen
- Feldnachweise und Parserhinweise
- Bilder, PDFs und weitere Medien
- Kandidatenzuordnungen und Preisverläufe
- fehlende Stammdaten der Hauptakte
- frühere KI-Analysen als archivierte Dateien

Vorhandene Werte der Hauptakte bleiben bestehen. Doppelte Medien werden über Datei-Hash oder Original-URL entfernt. Anschließend wird automatisch eine neue kombinierte KI-Analyse bereitgestellt.

## Titelbild wählen

Die Bildergalerie bleibt eine reine, aufgeräumte Galerie. Das Vorschaubild wird über die eigene Aktion **Titelbild** gewählt.

Auf der Auswahlseite:

- Bild antippen beziehungsweise Auswahl-Symbol verwenden
- gewähltes Bild wird markiert
- erscheint danach in Übersicht und Kopfbereich der Hausakte
- über **Automatische Auswahl** kann die feste Auswahl aufgehoben werden

## Hausakte bearbeiten

Die Aktion **Bearbeiten** öffnet ein eigenes Formular für:

- Titel
- Lage und Adressstatus
- Preis
- Wohn- und Grundstücksfläche
- Zimmer und Baujahr
- HWB und fGEE
- Heizung
- Notizen

## Suchprofile verwalten

Pfad:

```text
Einstellungen → Suchprofile
```

Ein bestehendes Profil kann jetzt vollständig bearbeitet werden:

- Name
- Regionen und Orte
- Willhaben-areaIds beziehungsweise Postleitzahlen
- eigene Such-URL
- Zielpreis und harte Preisgrenze
- Mindestwohnfläche und Wunsch-Grundstück
- HWB-Warn- und Ausschlusswert
- Ausschlussbegriffe
- Ölheizungsregel
- aktiv oder pausiert
- manueller, halbautomatischer oder vollautomatischer Modus
- Intervall und Trefferlimit
- Auto-Import-Score und maximales Importlimit

Neue Profile werden über **Neues Profil** angelegt. Profile können inklusive Kandidaten-, Preis- und Änderungsverlauf gelöscht werden; bestehende Hausakten bleiben erhalten.

## Kandidaten-Lifecycle

HausCheck unterscheidet:

```text
new          neu gefunden
review       manuell prüfen
changed      relevante Daten geändert
reactivated  nach Offline-Status wieder online
offline      in zwei erfolgreichen Suchläufen nicht mehr gefunden
imported     als Hausakte angelegt
rejected     abgelehnt
```

Preisänderungen, erneute Veröffentlichungen und relevante Datenänderungen werden hervorgehoben und im Verlauf gespeichert.

## Bewertungssystem

Vor der KI-Analyse verwendet HausCheck eine regelbasierte Daten-Vorprüfung. Nach dem Import einer ChatGPT-Analyse wird `new_score` zur maßgeblichen Hauptbewertung.

Die KI-Auswertung kann zusätzlich enthalten:

```text
fairer Kaufpreisbereich
erstes Verhandlungsangebot
realistischer Zielpreis
empfohlene Preisobergrenze
Investitionsposten mit Priorität und Kostenspanne
grobe Projektkosten aus Zielkaufpreis plus Investitionen
```

Die Kaufpreiseinschätzung ist kein Verkehrswertgutachten. Fehlende oder nicht sichtbare Bauteile werden nicht als gesichert behandelt.

## HWB- und Dezimalwerte

Für HWB und fGEE gelten Punkt und Komma als Dezimaltrennzeichen:

```text
306.1 → 306,1
306,1 → 306,1
```

Strukturierte Werte aus Tabellen, Definitionslisten und Wertelisten haben Vorrang vor allgemeinem Seitentext.

## GitHub AI Exchange

```yaml
github_exchange_enabled: true
github_auto_export_on_import: true
github_auto_import_results: true
github_auto_import_interval_minutes: 5
github_repo: "andreassamitsch/HausCheckAIExchange"
github_branch: "main"
github_token: "DEIN_GITHUB_TOKEN"
github_export_path: "ai_exchange/exports/pending"
github_result_path: "ai_exchange/results/pending"
github_done_path: "ai_exchange/results/done"
github_cleanup_after_import: true
```

## Datenablage

```text
/share/hauscheck/
├── hauscheck.db
└── projects/
    └── <house_id>/
        ├── html/
        ├── images/
        ├── pdfs/
        ├── exports/
        └── analysis/
```

## Hinweise

- Fehlende Werte bleiben leer und werden nicht erfunden.
- Ohne genaue Adresse erfolgt keine belastbare Lageprüfung.
- Captchas oder Login-Sperren werden nicht umgangen.
- Werbe- und KI-generierte Inseratbilder werden nicht als Zustandsnachweis verwendet.
- Kaufnebenkosten, Finanzierung und Steuern werden nur berücksichtigt, wenn dies ausdrücklich dokumentiert ist.
