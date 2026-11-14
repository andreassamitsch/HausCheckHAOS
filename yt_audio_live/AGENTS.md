# Agent-Playbook: YouTube Music Live auf Home Assistant

> Zweck: Musik per Chat-/Sprachbefehl **sofort** auf der Samsung Ultra Slim Soundbar starten. Diese Datei enthält eine dauerhaft abrufbare Arbeitsanweisung für künftige Assistenten. Keine Zugangsdaten hier ablegen.

## Wichtigste Regel

Bei einer klaren Anweisung wie „Spiel Queen – Bohemian Rhapsody“ **zuerst den tatsächlichen Wiedergabeaufruf ausführen**. Nicht bloß den Start ankündigen; nicht erst mehrfach suchen und dann gesondert starten. Die App führt die Titelsuche selbst aus.

## Installation (Stand: 14.11.2026)

- Home Assistant App: `YouTube Music Live (Test)`
- Supervisor App-Slug: `01c80471_yt_audio_live`
- Steuer-API auf dem App-Port `8765`
- Stream-Client: `visionos`
- Richtiger Google-Cast-Player: `media_player.ultra_slim_soundbar` (nicht `media_player.ultra_slim_soundbar_2`; dieser ist eine zweite Samsung-Entität und kann `on` sein, während die eigentliche Cast-Entität `off` ist)
- Übliche zuletzt verlangte Lautstärke: `0.05` (5 %). Falls eine neue Lautstärke genannt wird, diese verwenden, ansonsten den letzten Wunsch beibehalten.

## Schnellster Aufruf mit Home-Assistant-MCP

1. `ha_get_app(slug="01c80471_yt_audio_live")` aufrufen, um die aktuelle App-Konfiguration einschließlich des **privaten** `options.api_key` zu lesen. Schlüssel nur innerhalb des autorisierten Tool-Aufrufs verwenden, **niemals ausgeben, protokollieren, in GitHub einchecken oder im Chat wiederholen**.
2. Über `ha_manage_app` im **Proxy-Modus** direkt den Start senden (bei schreibendem Aufruf ggf. `ha_call_write_tool`):
   - `slug: "01c80471_yt_audio_live"`
   - `path: "/api/play"`
   - `port: 8765`
   - `method: "POST"`
   - `request_headers: {"X-API-Key": <API-Key aus den App-Optionen>}`
   - `body: {"query": "Queen Bohemian Rhapsody", "volume_level": 0.05, "radio": false}`
   - Bei einem anderen Lied lediglich `query` anpassen. Benutzerwunsch zu Lautstärke und Radio übernehmen.
3. `POST /api/play` kann zunächst `cast_state: "starting"` zurückgeben: Das ist **noch keine** bestätigte Wiedergabe. Unmittelbar danach `GET /api/status` mit demselben App-Slug, Port und Auth-Header aufrufen und `cast_state: "playing"` prüfen. Optional mit Home-Assistant-State `media_player.ultra_slim_soundbar` gegenprüfen. Erst dann einen bestätigten Start melden.
4. Falls `playing` nicht erreicht wird: App-Logs mit `ha_get_logs(source="supervisor", slug="01c80471_yt_audio_live")` auswerten. Besonders auf `POST /api/play`, `source_resolved`, `GET /stream/...`, `first_audio_bytes`, `stream_done` und Fehler achten. Eine `playing`-Meldung bestätigt Cast-Status, nicht zwingend hörbaren Ton.

## Weitere Befehle

- Stop: `POST /api/stop` mit `{}`
- Pause: `POST /api/pause` mit `{}`
- Fortsetzen: `POST /api/resume` mit `{}`
- Nächster Titel: `POST /api/next` mit `{}`
- Radio einschalten: `POST /api/radio` mit `{"enabled": true}`
- Playlist: `POST /api/playlist` mit `{"playlist_id": "...", "shuffle": false, "radio_after": true}`

Immer den tatsächlichen API-Aufruf durchführen und das Ergebnis prüfen, statt die Aktion allein zu beschreiben.

## Fehler und Geschwindigkeit

- Am 14.11.2026 wurde „Bohemian Rhapsody“ zunächst nur verbal angekündigt, ohne einen API-Start. Der Player blieb still. **Ursache: fehlender tatsächlicher Aufruf, kein Streaming- oder YouTube-Fehler.**
- Der anschließende direkte API-Aufruf mit `query="Queen Bohemian Rhapsody"`, `volume_level=0.05` war erfolgreich; `GET /api/status` meldete `playing`; HA meldete `media_player.ultra_slim_soundbar=playing` bei 5 %. Die Soundbar forderte den signierten Stream tatsächlich an und FFmpeg lieferte Audio (`exit_code=0`).
- Vermeide die frühere ineffiziente Folge: mehrfach `/api/search` aufrufen → lange zwischen Schritten warten → separat `/api/play`. Nur bei explizit mehrdeutigen Versionen oder Nutzerwunsch vorab suchen.
- Für einfache Sprachbefehle die **eine** `/api/play`-Anfrage priorisieren und keine unnötigen GitHub-/Web-/Diagnoseaufrufe vor den Start schalten.
- Niemals „spielt“ behaupten, solange nur „starting“ oder ein geplanter Aufruf bekannt ist.
