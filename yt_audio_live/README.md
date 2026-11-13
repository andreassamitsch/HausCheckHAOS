# YouTube Audio Live Proxy (Test)

A small Home Assistant OS App for testing low-latency playback of a **single preconfigured** YouTube video as a live MP3 stream on a Google Cast speaker. It does not download the whole video first.

## Configuration

The App option video_id is the 11-character YouTube video ID. Initially this App is configured for tba_zo_8ye4 (Nowhere Land). It does not expose an arbitrary-URL endpoint.

- App host port: 8765 TCP, **local network only**. Never set up router port forwarding.
- GET /health returns a short JSON status.
- GET /stream/<video_id>.mp3 streams audio/mpeg with HTTP chunked transfer.
- Only one simultaneous stream is permitted.
- The App starts only when manually started, does not alter Home Assistant configuration, and can be uninstalled.

## Test with Home Assistant

First set media_player.ultra_slim_soundbar volume to 0.07 (7%). Then use media_player.play_media with:

- Entity: media_player.ultra_slim_soundbar (Google Cast, not Alexa)
- media_content_id: http://<HOME_ASSISTANT_LAN_IP>:8765/stream/tba_zo_8ye4.mp3
- media_content_type: audio/mpeg

Verify actual playback and stop after the test with media_player.media_stop.

The App logs source_resolved and first_audio_bytes times. These are **not** the same as audible start latency. Note that some Google Cast receivers may reject chunked MP3 streams. YouTube extraction may stop working when YouTube changes.

## Requirements

Home Assistant OS amd64, outgoing access to YouTube, a LAN-connected Cast speaker. The container installs FFmpeg, Node.js >=22 (the Alpine package), yt-dlp and its default external JavaScript solver dependencies. This App is a proof of concept and has **no authentication** on the LAN port. Use only for streams that you are authorized to access.
