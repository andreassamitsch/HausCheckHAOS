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

## Tested YouTube 403 fix (13 Nov 2026)

The original default extraction returned video URLs, but Google Video Server rejected media GET requests with HTTP 403.
Both WebM/Opus format 251 and progressive MP4 format 18 failed. The web_embedded client also received 403; tv returned a yt-dlp DownloadError.

**Confirmed working for video ID tba_zo_8ye4:**
- Set the App option player_client to visionos (version 0.1.5 and later).
- yt-dlp extracts WebM/Opus format 251 using the VisionOS Innertube client.
- /probe successfully fetched 1024 audio bytes with HTTP 206 in approximately 2.4 seconds.
- FFmpeg produced audio/mpeg, first output bytes in 257 ms on a warm source cache.
- Proxy delivered about 5.5 MB with exit_code=0; Samsung Cast entity reached playing at 7% volume.
- Total time to audible start was not directly measured.

The /probe endpoint is diagnostic: it extracts a source and fetches 1024 bytes.
It returns only client, HTTP status, content type and timing, without exposing signed URLs.
The 90-second source cache is warmed by the probe.

YouTube client requirements change. If VisionOS stops working, see https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide .
A BgUtils GVS PO-token provider with the mweb client is the maintainer-recommended fallback.

This app exposes a fixed test video, not a general music search API; it remains in manual boot mode until hardened for normal use.
