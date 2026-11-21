# Changelog

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
