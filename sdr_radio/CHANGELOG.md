# Changelog

## 0.5.2 – 2026-11-22
- Google-Cast-Wiedergabe deklariert MP3-Radio als `audio/mpeg` und ausdrücklich `stream_type=LIVE` statt als endlichen Musik-Titel.
- MP3-HTTP-Stream verwendet weiterhin bewusst *keinen* Content-Length-Header und trägt die Radio-Bitrate als ICY-Header.
- Diagnostik zeichnet abgeschlossene MP3-Hörer-Sessions mit Start/Ende, Laufzeit, Datenmenge und TCP-Abbruchgrund im RAM auf.
- Kein automatisches Wiederanlaufen nach manuellem Stopp oder nach einem Geräteabbruch.

## 0.5.1 – 2026-11-21
- Beim manuellen Start Ausgabegeräten 12 Sekunden zum Aufwachen geben, damit eine verzögerte Playing-State-Meldung nicht als Stopp fehlinterpretiert wird.
- Stoppen am Ausgabegerät führt zu keinem automatischen Neubeginn der Wiedergabe; Play bleibt ausschließlich manuell.

## 0.5.0 – 2026-11-21
- Native Dashboard-Anbindung über MQTT Discovery: Sensor für RDS-Titel, Senderlogo, Albumcover, Frequenz, Favoriten und Audiozustand.
- Authentifizierte Kommandos via Home-Assistant-Dienst mqtt.publish (kein offener Steuerport).
- Getrennte manuelle Wiedergabe-/Stopplogik für ausgewählte media_player.
- Auswahl des Ausgabegeräts und letzte Frequenz werden als kleine JSON-Datei gespeichert.
- Bei Stop/Pause am Ausgabegerät kein Autoplay, erneuter Start ausschließlich per explizitem Play-Befehl.
- Gemeinsame Favoritenverwaltung mit optionaler konservativer Logo-Zuordnung.

## 0.4.1 – 2026-11-21
- Sendername mit identischem RDS-PI-Code und RTR-Frequenzbuch auf vollständigen öffentlichen Programmnamen ergänzen.
- RTR-Wies-Liste auf die 150 nächstgelegenen Senderdatensätze begrenzt (API-Größenlimit).
- Sendername auf dem Tablet bei nachträglich erkanntem RDS automatisch aktualisieren.

## 0.4.0 – 2026-11-21
- Echtzeit-RDS via redsea 1.3.1 aus UKW-MPX ohne zweiten SDR-Empfänger.
- PI / PS / RadioText / RT+ Titel/Interpret als Primärquelle; Online-Fallback gekennzeichnet.
- Albumcover zuerst mit YouTube Music über starke Artist-/Titelübereinstimmung, danach iTunes.
- Amtliches RTR-Frequenzbuch mit regionaler UKW-Liste für Wies, Senderstandorten und Distanz.
- Redsea-kompatibler MPX-Audiopfad mit 48-kHz-Ausgabe; RDS bei Bedarf abschaltbar.
- Neue Diagnose-/Quellenanzeige in der Radio-App.

## 0.3.1 – 2026-11-21
- Beim Build die Module `radio_metadata.py` und `sdr_scan.py` vollständig in das App-Image aufnehmen.

## 0.3.0 – 2026-11-21
- Sendersuchlauf aufwärts/abwärts via `rtl_power`-Spektrum mit RAM-Cache.
- Frequenzraster +/- 0,1 MHz und manuelle UKW-Bandsuche.
- Senderzuordnung aus Radio-Browser mit Logo und gespeichertem Frequenz-Mapping.
- Aktueller Song und Interpret über ICY-Metadaten des Online-Radiosenders (falls vorhanden).
- Titelcover via iTunes Search API, ohne Bilder oder Audiodateien auf dem Host zu speichern.
- Erweiterte Tablet-Oberfläche mit Titelcover, Senderlogo, Scan-Liste und Senderwahl.
- RDS/AF bewusst nicht integriert; Online-Songmetadaten werden als solche gekennzeichnet.

## 0.2.0 – 2026-11-21
- Fast-Tuning: Nur `rtl_fm` wird beim Frequenzwechsel neu gestartet, der MP3-Encoder bleibt aktiv.
- Dauerhafte MP3-Verbindungen mit Stille während des Abstimmens statt Unterbrechung.
- Echtzeit-PCM über WebSocket im authentifizierten Ingress und WebAudio mit kurzem Browserpuffer.
- Kleinere MP3-Ausleseblöcke, begrenzte Audio-Queues und keine künstliche 450-ms-Wartezeit.
- Status zeigt die Abstimmzeit bis zum ersten PCM-Datenblock an.
- Bewährte UKW-Audiofilter und 48-kHz-Demodulation unverändert.

## 0.1.3 – 2026-11-21
- Nicht unterstütztes 4×-Oversampling entfernt; behebt Fehler bei 3,84 MS/s am Nooelec RTL-SDR.

## 0.1.2 – 2026-11-21
- Audioqualität: 240-kHz-FM-Empfang mit exakter 5:1-Herunterskalierung auf 48 kHz.
- Standard-Atan-Demodulation statt Fast-Modus; 9-Tap-FIR, De-Emphasis und DC-Filter.
- Einstellbarer manueller RF-Gain zur Reduzierung möglicher Übersteuerung.
- MP3-Encoder übernimmt nun die 48-kHz-Rohdatenrate korrekt.

## 0.1.1 – 2026-11-21
- Ausgaberate von rtl_fm explizit auf 32 kHz festgelegt; vermeidet falsch dekodiertes MP3-Audio.
- Erzeugte Audio-Bytes werden in Diagnose/Bedienoberfläche sichtbar.
- Normale Startmeldungen des USB-Tuners werden nicht mehr als Fehler angezeigt.

## 0.1.0 – 2026-11-21
- Erste Home-Assistant-App für RTL-SDR-UKW-Radio.
- Weboberfläche mit Frequenzwahl, Favoriten und Senderstart/-stopp.
- Ein MP3-Livestream für mehrere Empfänger, mit getrennter öffentlicher Streaming-Schnittstelle.
- Wiedergabe auf Home-Assistant-Mediaplayern über die Core-API.
- SDR-Diagnose und Fehlerprotokoll im Webinterface.
- Kein automatischer Empfang beim App-Start; der vorhandene rtl_433-Dienst bleibt unberührt.
