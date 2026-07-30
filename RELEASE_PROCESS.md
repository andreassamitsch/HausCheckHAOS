# HausCheck Pro Release-Prozess

## Warum Updates wiederholt scheinbar fehlten

Home Assistant zeigt den zuletzt vom Supervisor geladenen Repository-Stand. Ein geöffnetes Update-Fenster oder ein älterer Zeitstempel wie `Update vor 30 Minuten` bedeutet nicht, dass ein wenige Minuten später veröffentlichter GitHub-Commit bereits geprüft wurde.

Der wiederholte Fehler lag im Ablauf: Ein Release wurde als verfügbar gemeldet, obwohl der letzte Home-Assistant-Repository-Check zeitlich noch vor dem Merge lag. Das Repository selbst enthielt bereits die neue Version, Home Assistant zeigte aber weiterhin den zuvor geladenen Stand.

## Verbindlicher Ablauf für jedes Release

1. Codeänderung, `hauscheck/config.yaml` und `hauscheck/CHANGELOG.md` werden im selben Release-Branch geändert.
2. Die Versionsnummer muss gegenüber `main` erhöht sein.
3. Der Release-Guard muss erfolgreich sein.
4. Der Pull Request wird nach erfolgreicher Prüfung nach `main` gemergt.
5. Der veröffentlichte `main`-Stand wird nochmals geprüft: `hauscheck/config.yaml` muss die neue Version enthalten.
6. Erst danach wird das Release als fertig beziehungsweise verfügbar gemeldet.
7. Bei Home Assistant muss der angezeigte Zeitpunkt des Repository-Checks nach dem Merge-Zeitpunkt liegen. Ab Version 0.17.2 kann der App-Store direkt in HausCheck unter `Einstellungen → HausCheck-Updates → Updates jetzt neu laden` aktualisiert werden.

## Release-Checkliste

- [ ] Versionsnummer in `hauscheck/config.yaml` erhöht
- [ ] passender Abschnitt in `hauscheck/CHANGELOG.md`
- [ ] Python-Syntaxprüfung erfolgreich
- [ ] relevante Regressionstests erfolgreich
- [ ] Pull Request gemergt
- [ ] `main/hauscheck/config.yaml` zeigt die neue Version
- [ ] Release-Guard auf dem Merge-Commit erfolgreich
- [ ] erst jetzt Benutzer über das Update informieren

## Technische Grundlage

Home Assistant ermittelt die verfügbare Add-on-Version aus dem Feld `version` in `hauscheck/config.yaml`. Der Supervisor hält geladene Store-/Repository-Informationen vor, bis ein Store-Reload beziehungsweise der nächste automatische Repository-Check erfolgt.
