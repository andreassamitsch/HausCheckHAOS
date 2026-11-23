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
GET /api/search?q=...&kind=songs      songs first, then videos if no songs are found
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

## Version 0.2.21 – Persistent playlist verification (23 November 2026)

- Persist the verified account and number of private playlists in the App's
  protected `/data/ytmusic-session-status.json` file (permissions `0600`).
- The Ingress **Status prüfen** page now preserves its accurate status across
  page reloads and music App updates; logout clears the status file.
- Live validation on this Home Assistant installation: saved Google session,
  **31 private playlists**, HTTP 200 for `/api/session/save`,
  `/api/session`, and `/api/library`.
- Separate outstanding playback issue: non-audible yt-dlp source probes on
  both a public track and a private library track return
  `Requested format is not available` with the configured `visionos` client.

## Version 0.2.20 – Firefox SQLite lock-safe sign-in (23 November 2026)

- Fixed `database is locked` when saving a Google login from the embedded Firefox browser.
- The App first attempts a normal read of Firefox's `cookies.sqlite`; when Firefox
  holds exclusive locks it creates a temporary, private copy of the DB with its
  SQLite WAL and SHM sidecars, reads it, and removes the snapshot automatically.
  Firefox does not have to exit and the user does not need to sign in again.
- Confirmed on this Home Assistant installation: authenticated session captured
  without manual cookie export, music API `/api/auth` recognizes the user, and
  `/api/library` retrieves 31 private playlists.
- Account access is **not** the same as successful audio extraction. A non-audible
  `/api/probe` of a public track and one library track still failed with
  `Requested format is not available` on the configured `visionos` yt-dlp
  client. Playback needs a separate provider/client compatibility fix.

## Version 0.2.19 – Mobile Firefox login (23 November 2026)

- A visible **⌨ Tastatur öffnen** button enables the native Android keyboard while the Google input field retains focus in the remote browser.
- Implements noVNC's supported touch-input handling with a local textarea, keyboard events and IME input fallback. Only the RFB websocket forwards typed keys to the private Firefox; there is no credential submission to the App API.
- **Enter**, **Tab** and **Backspace** buttons for reliable mobile navigation.
- Switch between **Einpassen** (scaled screen) and **100 %** (scroll/pan the virtual display) when the form is too small.
- Virtual display changed from 1280×800 to 680×900; Firefox starts in kiosk mode with larger UI for a portrait phone.
- Login workflow, stored session and streaming backend remain unchanged. Validated the App's /health endpoint, Ingress page, browser readiness and all noVNC input modules; mobile keystrokes still require a real-device test.

## Version 0.2.16 – Browser login directly in the Home Assistant App

**No JSON, request headers, cookie file, or external cookie manager required.**

The Home Assistant App now includes its own Firefox sign-in browser, streamed
through **Home Assistant Ingress** (the sidebar/open Web UI entry).

1. In Home Assistant go to **Settings → Apps → YouTube Music Live (Test)**.
2. Open the App's **Web UI**.
3. Sign into `https://music.youtube.com` in the real Firefox browser shown.
4. Press **Sitzung übernehmen** in the Home Assistant App, not on Google's site.
5. The App reads only YouTube-domain cookies from Firefox's private
   `cookies.sqlite`, writes `/data/ytmusic-session-cookies.txt` with file mode
   `0600`, and hot-reloads the catalog + yt-dlp cookie jar. No app restart,
   config editing or manual export is needed.

**Security:** Google credentials are entered directly into a real Firefox,
not into a custom password form. The remote browser websocket is reachable
only through Home Assistant's authenticated Ingress; the VNC server itself
listens only on container loopback. The browser profile and cookies persist
within this App's private data directory. Do not publish the App's login port
or reuse a posted cookie. The App's Web UI has a disconnect button that
removes the exported session; for complete logout from Google, use Google's
account sign-out in the browser too.

**Limitation:** Google can still reject some remote/new-device browser logins,
and a valid login does not guarantee that yt-dlp can extract every track
without a PO token. Account linkage and audio extraction remain separately
validated.

## Version 0.2.15 – Direct YTDLnis cookies.txt import (22 November 2026)

The **private** Home Assistant app option `ytmusic_auth_json` now accepts an entire
YTDLnis or other Netscape `cookies.txt` export in addition to browser JSON and
raw HTTP request headers. It generates the necessary YouTube Music auth headers
locally from the `__Secure-3PAPISID` cookie and provides a normalized cookie
jar to `yt-dlp`. WebView's 17-digit cookie expiry timestamps (microseconds
since 1601) are converted to standard Unix seconds. Cookies for other Google
domains are excluded. Credentials are never logged, written to GitHub, or
returned by the app API.

### Entering a multi-line cookie export

1. Sign out of the previously exposed browser session first, then export a
   **fresh** `cookies.txt` on your trusted device.
2. In Home Assistant go to **Settings → Apps → YouTube Music Live (Test) →
   Configuration**, switch to the YAML configuration editor if available,
   and preserve all existing settings.
3. Set only the secret option to a YAML literal block, preserving the
   *original tabs* in each cookie line:

   ```yaml
   ytmusic_auth_json: |-
     # Netscape HTTP Cookie File
     .youtube.com\tTRUE\t/\tTRUE\t0\tEXAMPLE_COOKIE\tplaceholder
   ```

4. Save the private configuration and restart **only this music App**.
5. Check account connectivity with `GET /api/auth` and playlist access with
   `GET /api/library`, using the app's existing protected API.

The example above contains **dummy data**. Never send real cookies in a chat
or commit them to GitHub. A working browser cookie does not guarantee playback:
YouTube may still require a PO token or deny extraction. The native HA media
browser's **Meine Playlists** page remains a separate integration patch pending
deployment.

## Version 0.2.14 – Easier account linking (22 November 2026)

The existing private `ytmusic_auth_json` option now accepts either a compact JSON object **or raw request headers** copied from a signed-in YouTube Music `/browse` POST request. The App converts raw headers locally with `ytmusicapi.setup(headers_raw=...)`. This avoids installing Python or converting the headers manually on the user's computer.

See [ytmusicapi's browser guide](https://ytmusicapi.readthedocs.io/en/stable/setup/browser.html). Prefer Firefox (Network → find an authenticated `/browse` POST → Copy Request Headers). Paste the copied text only in Home Assistant's private App option, never in a chat or GitHub.

## Version 0.2.13 – Account playlists & source protection (22 November 2026)

- Personal YouTube Music playlists use the existing private `ytmusic_auth_json` App option. Browser headers are kept in Home Assistant App configuration, **never** in GitHub or dashboard JavaScript.
- When browser session headers are configured, the App creates a private (0600) cookie jar inside its `/data` directory for yt-dlp. This may help with YouTube's new login challenge. It is **not** a guaranteed fix for PO-token requirements or IP restrictions.
- `GET /api/auth` now distinguishes catalog login from an available browser session for audio extraction.
- A blocked audio source reports HTTP 503 with an understandable message instead of a generic HTTP 502; an audio stream failure does not trigger another queued song.
- Private playlist entries expose cover thumbnails. A separate Home Assistant native media-player patch is in `yt_audio_live/ha_component_patch/media_player.py`, adding **Meine Playlists** to the browser. This patch is not automatically installed by updating the App.

### Account setup

1. Log in on **music.youtube.com** in a browser on your own trusted computer.
2. Follow [ytmusicapi's browser authentication guide](https://ytmusicapi.readthedocs.io/en/stable/setup/browser.html) to obtain the request headers of an authenticated `/browse` request.
3. Configure the **private** `ytmusic_auth_json` option in Home Assistant → Settings → Apps → YouTube Music Live (Test), then restart only that App. Never paste browser cookies, JSON session credentials, or API keys into a chat, issue, repository or screenshot.
4. Check `GET /api/auth` and `GET /api/library` locally through the authenticated API.
5. After deploying the separate Home Assistant integration patch and restarting Home Assistant at a convenient time, the media browser displays **Meine Playlists**. Without this patch, the existing `/api/library` and `/api/playlist` endpoints still work.

**Important:** Catalog sign-in is distinct from YouTube's permission to extract audio. YouTube may still require a PO token or block unattended extraction. Playing protected tracks is not guaranteed; account sessions may be logged out or blocked by YouTube.

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

## Version 0.2.7 – Stopp, Cover und Fortschritt

- Ein manuelles **Stopp** oder Ausschalten der Cast-Soundbar beendet die Wiedergabesitzung und die Radio-Automatik, statt sofort den nächsten Titel zu starten.
- Nur wenn die zuletzt beobachtete Position tatsächlich das Titelende erreicht, erfolgt ein automatischer Titelwechsel.
- Die Integration kann einen gezielten HA-Service-Stopp über `POST /api/external_stop` ohne erneuten Cast-Stopp synchronisieren.
- Die API liefert `media_position`, `media_position_updated_at` und ein YouTube-Music-Cover mit dem aktuellen Titel.
- `POST /api/seek {"position":120}` sucht im aktuellen Titel durch einen neu signierten Stream mit FFmpeg-Offset. Der Offset ist an die Signatur gebunden.
- Wiederaufnehmen ohne einen aktiven Titel wird abgelehnt, um eine unerwartete Wiederaufnahme nach Stopp zu verhindern.

**Hinweis:** Code- und Queue-Tests sind offline möglich. Die akustische Prüfung des echten Cast-Übergangs und des Suchlaufs muss erfolgen, wenn die Soundbar wieder verwendet werden darf.
