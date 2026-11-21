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
