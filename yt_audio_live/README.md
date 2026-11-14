# YouTube Music Live for Home Assistant OS

Local music playback for a Samsung Ultra Slim Soundbar via Home Assistant
Google Cast. This app intentionally separates the YouTube Music catalog
(ytmusicapi) from audio-stream extraction (yt-dlp + FFmpeg).

## Confirmed on 13 November 2026

- YouTube client: visionos. It resolved the HTTP 403 problems observed
  with android_vr, web_embedded and tv on the test video.
- Public catalog search (including fallback from songs to videos), public
  playlist search, playlist item retrieval and YouTube Music radio work.
- Starting an exact video by ID works via Home Assistant Cast.
- Playlist playback works, and the next songs and radio suggestions are
  added to an in-memory queue.
- Music starts without sending a volume change; the soundbar manages its own level.
- Actual automatic transitions at the natural end of a song are not yet
  fully verified; they rely on the media player changing from playing
  to idle after it finishes playback.

## Setup

Home Assistant Settings -> Apps -> YouTube Music Live (Test).

App options:
- player_client: visionos
- player_entity: media_player.ultra_slim_soundbar
- stream_base_url: http://192.168.1.66:8765
- api_key: a secret random 32+ character key (already set on the test install)
- ytmusic_auth_json: optional YouTube Music browser credentials

Do not forward port 8765 on the router. Control endpoints require the
X-API-Key header or Authorization Bearer token. Stream links are signed
and expire after one hour. Keep credentials and tokens out of GitHub.

## API

The following endpoints require API authentication.

GET /api/auth                         account connection status
GET /api/search?q=...&kind=songs      song search (fallback to videos)
GET /api/search?q=...&kind=playlists  public playlist search
GET /api/playlist?id=...&limit=100    playlist preview
GET /api/library                      own library playlists (requires account)
GET /api/recommendations?video_id=... radio/mix preview
GET /api/status                       current title, queue, radio status
GET /api/probe?video_id=...           diagnostic 1024-byte source test

POST /api/play      {"video_id":"tba_zo_8ye4","radio":true}
POST /api/play      {"query":"Gigi D Agostino Nowhere Land","radio":true}
POST /api/queue     {"video_id":"<YouTube video ID>"}
POST /api/queue     {"query":"song or artist"}
POST /api/queue/remove  {"index":0}                  remove queued track (0-based)
POST /api/queue/move    {"from_index":1,"to_index":0} reorder upcoming tracks
POST /api/queue/clear   {}                           clear upcoming tracks only
POST /api/playlist  {"playlist_id":"<playlist ID>","shuffle":false,"radio_after":true}
POST /api/radio     {"enabled":true}
POST /api/radio     {"video_id":"<video ID>","start_now":true,"enabled":true}
POST /api/next      {}
POST /api/stop      {}
POST /api/pause     {}
POST /api/resume    {}

Queries with a title automatically play the first search result. To avoid
unwanted versions, use /api/search and then play an exact video ID.

## Optional YouTube Music sign-in

Unregistered catalog searches, playlists and radio work without a login.
To access personal playlists, ytmusicapi browser authentication is supported.
On your own computer, sign into music.youtube.com and copy the request
headers from an authenticated network /browse request, as explained by
https://ytmusicapi.readthedocs.io/en/stable/setup/browser.html .
Provide the header dictionary in JSON form in the HA App's private
ytmusic_auth_json option and restart the App. Then verify /api/auth and
/api/library. Never paste cookies or authorization headers in chat or
GitHub. Personal catalog login does not guarantee access to restricted
yt-dlp playback streams.

## Design and limitations

music_catalog.py  ytmusicapi lookup/playlist/radio adapter
playback.py       Home Assistant media-player control, queue and auto-next
server.py         authenticated HTTP API, yt-dlp/FFmpeg streaming
Dockerfile        Python, FFmpeg, Node, yt-dlp, ytmusicapi

The app uses the supervisor's Home Assistant API permission solely to
control its configured media_player. All app requests remain local.

The app keeps its queue in RAM; restarting clears it. Radio playback
relies on the Cast state changing to idle at a song's end. yt-dlp's
visionos client currently works but YouTube may change its enforcement
of PO tokens. This is an unofficial integration; follow YouTube's terms.
