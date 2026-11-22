# SDR UKW Radio

Diese experimentelle App nutzt einen USB-Stick auf Basis von RTL2832U/kompatiblem RTL-SDR zum Empfang von **UKW-Radio 87,5–108 MHz**. `rtl_433` selbst decodiert nur Funksensordaten; hier wird das Programm `rtl_fm` benutzt.

## Voraussetzungen

- SDR-USB-Dongle mit Empfangsbereich 87,5–108 MHz und geeigneter UKW-Antenne
- USB-Passthrough an die Home-Assistant-OS-VM, falls HA auf Proxmox läuft
- Nur **eine Anwendung zur selben Zeit** kann einen einzelnen RTL-SDR-Stick verwenden. Bestehendes rtl_433 daher während des Radioempfangs stoppen (es ist derzeit ohnehin gestoppt).

## Installation

Diese App stammt aus dem bereits eingebundenen Repository `HausCheckHAOS`. Im App-Store nach Updates suchen, SDR UKW Radio installieren und starten. Dann in der App-Oberfläche die Schaltfläche **USB-Empfänger prüfen** verwenden und eine Frequenz wählen.

## Einstellungen

- `device_index`: RTL-SDR-Gerätenummer (bei einem Gerät 0)
- `gain`: Empfohlen `20.7` dB (R820T); bei schwachem Empfang `28.0` dB probieren, bei Verzerrung `14.4` dB. `auto` kann bei starken Sendern zu Übersteuerung führen.
- `ppm`: Frequenzkorrektur
- `stream_base_url`: Vom Abspielgerät erreichbare HTTP-URL, typischerweise `http://192.168.1.66:8099`. Nicht `localhost` verwenden.

**Zugriff:** Port 8099 gibt ausschließlich `/stream.mp3` und `/health` frei. Die Steuerung und Home-Assistant-Zugriffe laufen nur über den authentifizierten App-Ingress auf Port 8098. Port 8099 nicht ins Internet weiterleiten.

## Bedienung

1. Senderfrequenz eingeben und **Empfang starten** drücken.
2. Lokal über **Hier anhören** abspielen. Favoriten im Webinterface speichern.
3. Für einen separaten Lautsprecher das gewünschte `media_player`-Ziel wählen und **Auf Gerät abspielen** drücken.
4. Unter **Stream-URL** findest du den URL für Geräte, die einen normalen MP3-Radiostream unterstützen.

Die Audio-Wiedergabe startet nie automatisch beim Installieren oder Starten der App. Eine Senderumschaltung wirkt sich auf **alle** Zuhörer des einzigen Tuners aus. Die MP3- und PCM-Verbindungen bleiben seit 0.2.0 bestehen und übertragen während des Neuabstimmens kurz Stille.

## Einschränkungen

- Mono-MP3-Stream; kein RDS, kein DAB+, keine Frequenzsuche im ersten Release.
- Funktion von `media_player.play_media` hängt vom Lautsprecher und seiner Integration ab.
- Ein einzelner Dongle kann nicht gleichzeitig 433-MHz-Daten empfangen.
- Der MP3-Stream ist unverschlüsselt und für das Heimnetz gedacht; der Server gibt keine anderen Steuer-Endpunkte am öffentlichen Stream-Port frei.


## Empfangsqualität ab 0.1.2

Die Verarbeitung wurde vom schnellen WBFM-Preset auf eine explizite 240-kHz-FM-Demodulation mit 9-Tap-FIR, `std`-Demodulator, De-Emphasis und DC-Filter umgestellt. 240 kHz wird exakt auf 48 kHz heruntergerechnet. Die MP3-Eingangsrate entspricht jetzt **48 kHz**. Für den Nooelec R820T ist als Startwert eine manuelle Verstärkung von 20,7 dB sinnvoll; je nach Signalstärke anpassen. Dieser Wechsel behebt nicht notwendigerweise externe HF-Störungen.


## Schnelles Umschalten (ab 0.2.0)

- Senderwechsel startet nur den `rtl_fm`-Prozess neu, nicht mehr den MP3-Encoder. Der Netzstream und die verbundenen Abspielgeräte bleiben durchgehend verbunden.
- Während des Neuabstimmens generiert ein kleiner, zeitgesteuerter PCM-Puffer Stille. Verbindungen müssen nicht neu aufgebaut werden.
- Direkt im Dashboard nutzt `Hier anhören` nach Möglichkeit 48-kHz-Mono-PCM über einen WebSocket innerhalb des authentifizierten Home-Assistant-Ingress. Der Browser-Puffer wird auf rund 120 ms begrenzt.
- Unterstützt der Browser die Direktwiedergabe nicht, wird automatisch der bisherige MP3-Stream verwendet.
- Die Statuszeile zeigt die gemessene Zeit vom Umschaltbefehl bis zum ersten PCM-Datenblock (`SDR xx ms`). Die tatsächliche hörbare Verzögerung umfasst zusätzlich kleine Audio-/Gerätepuffer.
- Bei `media_player`-Ausgabe auf Soundbar oder externen Lautsprechern kann deren eigener Streaming-Puffer zusätzliche Sekunden verursachen. Home Assistant kann das nicht für jedes Gerät beeinflussen.
- Beim Senderwechsel auf derselben Frequenz erfolgt kein erneuter Tuner-Neustart.

Die bisherige FM-Demodulation inklusive De-Emphasis, FIR-Filter und Gain bleibt unverändert. Port 8099 bietet weiterhin nur MP3. Der PCM-WebSocket ist ausschließlich über das authentifizierte Home-Assistant-Ingress erreichbar.

## UKW-Radiofunktionen 0.3.0

- **Frequenz +/-:** je 100 kHz schalten, mit automatischem Rücksprung von 108,0 nach 87,5 MHz.
- **Sender +/-:** automatischer Suchlauf in die nächste Richtung. Ein `rtl_power`-Spektrumsweep ermittelt stärkere UKW-Signale; die Ergebnisse werden eine Stunde im Arbeitsspeicher gehalten. Der erste Suchlauf unterbricht den Empfang kurz, der Stream bleibt aber verbunden. Funkstörungen können gelegentlich als Sender erkannt werden.
- **UKW-Band durchsuchen:** Liste starker Signale, durch Antippen direkt anwählbar. Es werden **Empfangsleistungen**, nicht Sendernamen erkannt.
- **Sendername und Logo:** nach dem Einstellen einer Frequenz über das österreichische Radio-Browser-Verzeichnis suchen und den richtigen Sender zuordnen. Die Zuordnung wird als kleine JSON-Datei unter `/data/stations.json` dauerhaft gespeichert.
- **Songinfos und Albumcover:** Titel und Künstler werden (wo verfügbar) ausschließlich aus den ICY-Metadaten des zugeordneten *Online*-Radiostreams ausgelesen. Albumcover werden anhand der erkannten Metadaten über die iTunes Search API gesucht, und nur bei plausibler Übereinstimmung gezeigt.
- **Keine Mediendateien:** Der UKW-Audiostream bleibt aus dem USB-Dongle; auch die externen Metadatenabfragen speichern keine Streams oder Cover als Dateien.
- **Ohne RDS:** Die App decodiert derzeit keine RDS-PS/RT/RT+-Daten aus dem UKW-Signal. Unbekannte Frequenzen benötigen deshalb eine einmalige manuelle Senderzuordnung. RDS-AF ist wegen der stationären Nutzung absichtlich nicht Teil dieser Version.
- **Mögliche Abweichungen:** Die Online-Streams können gegenüber UKW zeitlich verzögert laufen; die angezeigten Songs können leicht vor- oder nachlaufen. Einige Radiosender liefern keine lesbaren ICY-Metadaten.

Die Suchfunktion ist besonders von der Antenne, der Verstärkung und der lokalen Senderdichte abhängig. Auf dem ersten Suchlauf pausiert der USB-Empfang wegen des einzigen RTL-SDR-Sticks. Die bereits optimierte 48-kHz-FM-Audiopipeline und die Tablet-PCM-Ausgabe werden beibehalten.


## RDS und RTR-Frequenzbuch (0.4.0)

- RDS wird mit [redsea](https://github.com/windytan/redsea) aus demselben FM-Multiplexsignal des RTL-SDR-Sticks dekodiert: PS-Senderkennung, PI-Code, Radiotext, RT+ Songtitel/Interpret.
- Nur **ein SDR-Stick**: der Multiplex wird zu redsea und danach zum Audiokonverter geleitet; MP3/PCM-Stream-Adressen bleiben unverändert.
- Das Live-Radio bleibt offline hörbar. **Titel und Sendername aus RDS haben Vorrang**. Die Online-Radiostream-Metadaten können ersatzweise genutzt werden, wenn RDS keine verwertbaren Songinformationen liefert, und sind im UI als Online-Fallback gekennzeichnet.
- Cover: zuerst YouTube Music (mit strenger Übereinstimmung Artist/Titel wie in Dudu7), danach iTunes. Nur Bild-URLs, keine Datei-Caches.
- RTR: Das amtliche österreichische Frequenzbuch wird auf Abruf bzw. beim App-Start eingelesen und auf **Wies (46.72028, 15.27194)** und einen Radius von 100 km um den Ortskern gefiltert. Anzeige in der UI: nächstgelegene Senderstandorte, Programmname und MHz. Der offizielle Katalog ist keine Empfangsgarantie; SDR-Spektrumsuche liefert tatsächliche Empfangstreffer.
- Empfang von RDS hängt vom ausgestrahlten Signal und der Antenne ab. Nicht jeder Sender überträgt RT+ oder überhaupt Titel-/Interpretinfos.
- **Option `rds_enabled`**: true (Standard) mit MPX/Redsea-Verarbeitung. Bei Audioproblemen kann RDS ausgeschaltet werden; nach Neustart wird der bewährte Audiopfad aus 0.3.1 verwendet.
- RDS/PI/Radiotext-Daten werden nicht aufgezeichnet oder auf die Festplatte geschrieben.


## Lovelace-Family-Dashboard-Anbindung (0.5.0)

Die Radio-App stellt via optionalem Supervisor MQTT-Service ein automatisch entdecktes Sensor-Entity `sensor.sdr_radio` bereit. Im Sensor stehen Frequenz, RDS-Sender, Titel, Interpret, Cover, Favoriten, der gewählte Ausgabemediaplayer und dessen Wiedergabezustand als Attribute. Alle Kommandos werden im authentifizierten Home-Assistant-Dienst `mqtt.publish` über das Topic `hauscheck/sdr_radio/command` an die App gesendet. Der direkte, nicht authentifizierte Port 8099 bleibt ausschließlich für den MP3-Audiostream. Die App bietet *keinen zusätzlichen offenen Steuerport*.

MQTT ist optional, die bestehende Ingress-Radio-App funktioniert auch ohne Broker. Die App spielt den Stream **niemals automatisch wieder an**, wenn ein Ausgabegerät extern stoppt oder pausiert. Wiedergabe startet nur auf eine ausdrückliche Aktion des Benutzers hin. Die Lautstärke gehört dem gewählten HA-`media_player`; die App verändert sie beim Start nicht.

Die letzte Frequenz und die ausgewählte Ausgabe werden in `/data/output.json` gespeichert. Albumcover werden weiterhin direkt von YouTube Music (Fallback iTunes) als URLs übertragen und nicht lokal gespeichert.


### Family-Dashboard-Karte installieren oder wiederherstellen

Der Quellcode für die im Family Dashboard bereits eingerichtete Karte liegt unter `sdr_radio/dashboard/hauscheck-sdr-radio-card-v2.js`. Er ist im laufenden Home Assistant als `/config/www/hauscheck-sdr-radio-card-v2.js` gespeichert und über das Lovelace-Ressourcenmodul `/local/hauscheck-sdr-radio-card-v2.js` registriert.

Dashboard-Kartentyp `custom:hauscheck-sdr-radio-card`, Sensor `sensor.sdr_ukw_radio_sdr_radio`. Die Karte befindet sich unter `family-dashboard/medien` unmittelbar nach YouTube Music und Toniebox, und zusätzlich in `family-dashboard/test`.

Die Dropdown-Geräteauswahl wählt lediglich das nächste Ziel, ohne Audio automatisch zu starten. Nur ein Klick auf Play führt `media_player.play_media` aus. Stopp auf der Karte oder direkt am Ausgabegerät wird respektiert; das Radio startet daraufhin nicht selbst erneut. Die Lautstärke wird mit dem Home-Assistant-Dienst `media_player.volume_set` direkt am gewählten Ausgabegerät eingestellt; ein ausgeschaltetes Gerät ohne `volume_level` zeigt einen deaktivierten Regler.

Das Sender-Favoritenpopup nutzt die in `/data/presets.json` gespeicherten Favoriten, ergänzt mit Senderlogos aus den zugeordneten Radioprogrammen. Weder das Dashboard noch die MQTT-Brücke schreiben MP3-/PCM-/Coverdateien auf den Host.


## Google-Cast-Langzeitstream (0.5.2)

Die Samsung S800D wird in Home Assistant primär über die **Cast-Integration** als `media_player.ultra_slim_soundbar` gesteuert. Zwei Abbrüche am 22.11.2026 erfolgten jeweils nach ca. 29 Minuten und fünf Sekunden Wiedergabe. Die SDR-/FFmpeg-Verarbeitung lief dabei weiter; Cast ging auf `idle`.

Die App sendet daher beim expliziten Benutzer-Play jetzt `media_content_type: audio/mpeg` und `extra: {stream_type: LIVE}`, um den Default Media Receiver als unbegrenztes Radio/Live-Audio statt als einzelnen begrenzten Musiktitel zu betreiben. Port 8099 sendet weiterhin unbegrenzte MP3-Daten ohne `Content-Length`. Bei einer Trennung dokumentiert `/api/status` den Zeitpunkt, die Dauer, die bis dahin übertragenen Bytes und den Verbindungsabbruchgrund in `recent_streams`. Die Historie liegt nur im RAM (16 Einträge). **Kein Autoplay/Auto-Reconnect des Lautsprechers bei Stop oder unerwartetem Idle.** Für den Effekt der neuen Cast-Deklaration ist noch ein erneuter expliziter Wiedergabestart nötig.

Bei erneutem Abbruch ist zuerst in `recent_streams` zu prüfen, ob die Cast-Verbindung nach einer exakt begrenzten Datenmenge oder zeitlich begrenzten Laufzeit getrennt wurde.
