# YouTube Music Live – Home Assistant Integration (experimental)

This integration sits **on top of** the existing YouTube Music Live Home Assistant app,
not in place of it. The app continues to handle YouTube search, audio streaming,
the queue, radio suggestions, and the Samsung Soundbar Cast connection.

## Features

- Virtual media player: current title/artist, play, pause, stop and next.
- `media_player.play_media`: media type `music` = text search, `youtube_id` = exact
  YouTube video ID, `playlist` = playlist ID. A new selection starts radio.
- `sensor.*_warteschlange`: number of queued tracks; up to 50 track details in
  its `tracks` attribute (the actual queue is still stored in the app's RAM).
- `switch.*_radio`: enable or disable automatic follow-up songs.

**Volume stays on the existing physical** `media_player.ultra_slim_soundbar`.
This integration intentionally offers no volume controls.

## Installation

Copy this folder to Home Assistant as
`config/custom_components/yt_audio_live/`, then restart Home Assistant.
Go to **Settings → Devices & Services → Add Integration → YouTube Music Live**.
Enter the app URL (on HAOS usually `http://01c80471-yt-audio-live:8765` via Supervisor DNS,
or your HA host's LAN IP and port 8765) and the app's `api_key` from its private configuration.
Do not publish the key; it is kept in Home Assistant's config entry.

The integration polls the authenticated app `GET /api/status` every 5 seconds.
Commands call the documented `POST /api/*` endpoints. No music-app code changes,
restart or redeployment are necessary.

## Limitations

- The app API does not provide removing or reordering individual queued tracks;
  this integration therefore cannot offer those controls yet.
- The virtual player reflects the app's reported Cast state, which may not
  perfectly match a playback transition. Use the physical media player for volume.
- Automatic track transitions depend on the app's Cast monitor and remain
  subject to its existing behavior. The queue is lost on music-app restart.
- Install and configuration flow have not yet been tested inside Home Assistant
  in this development branch.
