"""Home Assistant-native YouTube Music player with browsable queue and Cast volume."""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

from homeassistant.components.media_player import (
    BrowseError,
    MediaClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.components.media_player.browse_media import (
    BrowseMedia,
    SearchMedia,
    SearchMediaQuery,
)
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

QUEUE = "queue"
HISTORY = "history"
SEARCH = "search"
LIBRARY = "library"
LIBRARY_PLAYLIST_PREFIX = "library_playlist:"
MEDIA_PREFIX = "song:"
QUEUE_PREFIX = "queue:"
HISTORY_PREFIX = "history:"


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([MusicPlayer(hass.data[DOMAIN][entry.entry_id], entry)])


class MusicPlayer(CoordinatorEntity, MediaPlayerEntity):
    _attr_name = "Ultra Slim Soundbar"
    _attr_icon = "mdi:music-circle"
    _attr_has_entity_name = False
    _attr_should_poll = False
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.PREVIOUS_TRACK
        | MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.PLAY_MEDIA
        | MediaPlayerEntityFeature.SEEK
        | MediaPlayerEntityFeature.BROWSE_MEDIA
        | MediaPlayerEntityFeature.SEARCH_MEDIA
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.VOLUME_MUTE
    )

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_player"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="YouTube Music Live", manufacturer="Home Assistant DIY",
            model="YouTube Music Live API"
        )
        self._search_cache: dict[str, dict] = {}

    @property
    def state(self):
        data = self.coordinator.data or {}
        if not data.get("current"):
            return MediaPlayerState.IDLE
        match data.get("cast_state"):
            case "playing":
                return MediaPlayerState.PLAYING
            case "paused":
                return MediaPlayerState.PAUSED
            case "starting":
                # Home Assistant's native media-control hides all transport
                # buttons while buffering. A track already exists and is
                # starting (or seeking), so keep its Pause/Previous/Next
                # buttons present instead of flickering on every Cast restart.
                return MediaPlayerState.PLAYING
            case _:
                return MediaPlayerState.IDLE

    @property
    def media_title(self):
        return ((self.coordinator.data or {}).get("current") or {}).get("title")

    @property
    def media_artist(self):
        return ((self.coordinator.data or {}).get("current") or {}).get("artist")

    @property
    def media_duration(self):
        return ((self.coordinator.data or {}).get("current") or {}).get("duration_seconds")

    @property
    def media_position(self):
        data = self.coordinator.data or {}
        return data.get("media_position") if data.get("current") else None

    @property
    def media_position_updated_at(self):
        data = self.coordinator.data or {}
        stamp = data.get("media_position_updated_at")
        if stamp and data.get("current"):
            try:
                return datetime.fromtimestamp(float(stamp), tz=timezone.utc)
            except (TypeError, ValueError, OverflowError):
                pass
        return None

    @property
    def media_content_id(self):
        return ((self.coordinator.data or {}).get("current") or {}).get("video_id")

    @property
    def media_content_type(self):
        return MediaType.MUSIC if (self.coordinator.data or {}).get("current") else None

    @property
    def media_image_url(self):
        return ((self.coordinator.data or {}).get("current") or {}).get("thumbnail")

    @property
    def media_image_remotely_accessible(self):
        return True

    @property
    def _soundbar_entity(self):
        return (self.coordinator.data or {}).get("player_entity")

    @property
    def _soundbar_state(self):
        entity_id = self._soundbar_entity
        return self.hass.states.get(entity_id) if entity_id else None

    @property
    def volume_level(self):
        state = self._soundbar_state
        return state.attributes.get("volume_level") if state else None

    @property
    def is_volume_muted(self):
        state = self._soundbar_state
        return state.attributes.get("is_volume_muted") if state else None

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data or {}
        return {
            "queue_length": d.get("queue_length", 0),
            "history_length": d.get("history_length", 0),
            "radio_enabled": d.get("radio_enabled", False),
            "soundbar_entity_id": d.get("player_entity"),
            "last_error": d.get("last_error"),
            "cover_url": (d.get("current") or {}).get("thumbnail"),
        }

    async def _soundbar_service(self, action, **params):
        entity_id = self._soundbar_entity
        if not entity_id:
            return
        await self.hass.services.async_call(
            "media_player", action, {"entity_id": entity_id, **params}, blocking=True
        )
        self.async_write_ha_state()

    async def async_set_volume_level(self, volume: float) -> None:
        await self._soundbar_service("volume_set", volume_level=max(0.0, min(1.0, volume)))

    async def async_volume_up(self) -> None:
        await self.async_set_volume_level(min(1.0, (self.volume_level or 0.0) + 0.01))

    async def async_volume_down(self) -> None:
        await self.async_set_volume_level(max(0.0, (self.volume_level or 0.0) - 0.01))

    async def async_mute_volume(self, mute: bool) -> None:
        await self._soundbar_service("volume_mute", is_volume_muted=mute)

    async def async_media_play(self):
        await self.coordinator.command("/api/resume")

    async def async_media_pause(self):
        await self.coordinator.command("/api/pause")

    async def async_media_stop(self):
        await self.coordinator.command("/api/stop")

    async def async_media_next_track(self):
        await self.coordinator.command("/api/next")

    async def async_media_previous_track(self):
        await self.coordinator.command("/api/previous")

    async def async_media_seek(self, position: float) -> None:
        await self.coordinator.command("/api/seek", {"position": int(position)})

    @staticmethod
    def _item(track: dict, identifier: str) -> BrowseMedia:
        duration = track.get("duration_seconds")
        timing = ""
        if isinstance(duration, (int, float)) and duration > 0:
            timing = f" · {int(duration)//60}:{int(duration)%60:02d}"
        artist = track.get("artist", "")
        title = f'{track.get("title") or "Unbekannter Titel"}'
        if artist:
            title += f" — {artist}"
        return BrowseMedia(
            media_class=MediaClass.TRACK,
            media_content_type=MediaType.MUSIC,
            media_content_id=identifier,
            title=title + timing,
            can_play=True,
            can_expand=False,
            thumbnail=track.get("thumbnail"),
        )

    async def async_browse_media(
        self, media_content_type: MediaType | str | None = None,
        media_content_id: str | None = None
    ) -> BrowseMedia:
        """Native Home Assistant media browser (the same UI Tonie uses)."""
        # Refresh on opening the browser; no music control command.
        await self.coordinator.async_request_refresh()
        data = self.coordinator.data or {}
        queue = data.get("queue") or []
        history = data.get("history") or []
        if media_content_id == SEARCH:
            return BrowseMedia(
                media_class=MediaClass.DIRECTORY,
                media_content_type=MediaType.MUSIC,
                media_content_id=SEARCH,
                title="Titel suchen",
                can_play=False,
                can_expand=True,
                can_search=True,
                search_media_classes=[MediaClass.TRACK],
                children_media_class=MediaClass.TRACK,
                children=[],
            )
        if media_content_id == LIBRARY:
            from .api import MusicAPIError
            try:
                response = await self.coordinator.client.request(
                    "GET", "/api/library?limit=100"
                )
            except MusicAPIError as exc:
                raise BrowseError(
                    "YouTube Music nicht verbunden. Bitte melde dich zuerst "
                    "in der YouTube-Music-Live-App an."
                ) from exc
            playlists = [p for p in response.get("playlists", [])
                         if isinstance(p, dict) and p.get("playlist_id")]
            return BrowseMedia(
                media_class=MediaClass.DIRECTORY,
                media_content_type=MediaType.MUSIC,
                media_content_id=LIBRARY,
                title=f"Meine Playlists ({len(playlists)})",
                can_play=False,
                can_expand=True,
                children_media_class=MediaClass.PLAYLIST,
                children=[
                    BrowseMedia(
                        media_class=MediaClass.PLAYLIST,
                        media_content_type=MediaType.PLAYLIST,
                        media_content_id=LIBRARY_PLAYLIST_PREFIX + p["playlist_id"],
                        title=str(p.get("title") or p["playlist_id"]),
                        can_play=True,
                        can_expand=True,
                        thumbnail=p.get("thumbnail"),
                    ) for p in playlists
                ],
            )
        if (media_content_id or "").startswith(LIBRARY_PLAYLIST_PREFIX):
            from .api import MusicAPIError
            playlist_id = media_content_id[len(LIBRARY_PLAYLIST_PREFIX):]
            try:
                playlist = await self.coordinator.client.request(
                    "GET", "/api/playlist?id=" + quote(playlist_id) + "&limit=200"
                )
            except MusicAPIError as exc:
                raise BrowseError("Playlist konnte nicht geladen werden: " + str(exc)) from exc
            tracks = [t for t in playlist.get("tracks", [])
                      if isinstance(t, dict) and isinstance(t.get("video_id"), str)]
            self._search_cache.update({t["video_id"]: t for t in tracks})
            return BrowseMedia(
                media_class=MediaClass.PLAYLIST,
                media_content_type=MediaType.PLAYLIST,
                media_content_id=media_content_id,
                title=str(playlist.get("title") or "Playlist"),
                can_play=bool(tracks),
                can_expand=True,
                children_media_class=MediaClass.TRACK,
                children=[self._item(t, MEDIA_PREFIX + t["video_id"]) for t in tracks],
            )
        if media_content_id == QUEUE:
            return BrowseMedia(
                media_class=MediaClass.DIRECTORY, media_content_type=MediaType.MUSIC,
                media_content_id=QUEUE, title=f"Warteschlange ({data.get('queue_length', 0)})",
                can_play=False, can_expand=True, children_media_class=MediaClass.TRACK,
                children=[
                    self._item(track, f"{QUEUE_PREFIX}{i}:{track['video_id']}")
                    for i, track in enumerate(queue) if isinstance(track, dict)
                ],
                not_shown=max(0, int(data.get("queue_length", 0)) - len(queue)),
            )
        if media_content_id == HISTORY:
            return BrowseMedia(
                media_class=MediaClass.DIRECTORY, media_content_type=MediaType.MUSIC,
                media_content_id=HISTORY, title="Zuletzt gespielt",
                can_play=False, can_expand=True, children_media_class=MediaClass.TRACK,
                children=[
                    self._item(track, f"{HISTORY_PREFIX}{i}:{track['video_id']}")
                    for i, track in enumerate(history) if isinstance(track, dict)
                ],
            )
        if media_content_id not in (None, ""):
            raise BrowseError("Unknown YouTube Music browse location")
        # Home Assistant's frontend intentionally hides search at the browse
        # root. A browsable SEARCH subfolder exposes the native search field
        # after one tap, including when the playback queue is empty.
        return BrowseMedia(
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.MUSIC,
            media_content_id="",
            title="YouTube Music Live",
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.DIRECTORY,
            children=[
                BrowseMedia(
                    media_class=MediaClass.DIRECTORY,
                    media_content_type=MediaType.MUSIC,
                    media_content_id=LIBRARY,
                    title="Meine Playlists",
                    can_play=False,
                    can_expand=True,
                    children_media_class=MediaClass.PLAYLIST,
                ),
                BrowseMedia(
                    media_class=MediaClass.DIRECTORY,
                    media_content_type=MediaType.MUSIC,
                    media_content_id=SEARCH,
                    title="Titel suchen",
                    can_play=False,
                    can_expand=True,
                    can_search=True,
                    search_media_classes=[MediaClass.TRACK],
                    children_media_class=MediaClass.TRACK,
                ),
                BrowseMedia(
                    media_class=MediaClass.DIRECTORY,
                    media_content_type=MediaType.MUSIC,
                    media_content_id=QUEUE,
                    title=f"Warteschlange ({data.get('queue_length', 0)})",
                    can_play=False,
                    can_expand=True,
                    children_media_class=MediaClass.TRACK,
                ),
                BrowseMedia(
                    media_class=MediaClass.DIRECTORY,
                    media_content_type=MediaType.MUSIC,
                    media_content_id=HISTORY,
                    title=f"Zuletzt gespielt ({len(history)})",
                    can_play=False,
                    can_expand=True,
                    children_media_class=MediaClass.TRACK,
                ),
            ],
        )

    async def async_search_media(self, query: SearchMediaQuery) -> SearchMedia:
        """Search songs without starting playback."""
        term = str(query.search_query or "").strip()
        if not term:
            return SearchMedia(result=[])
        from urllib.parse import quote
        from .api import MusicAPIError
        try:
            response = await self.coordinator.client.request(
                "GET", f"/api/search?q={quote(term)}&kind=songs&limit=20"
            )
        except MusicAPIError as exc:
            raise BrowseError(str(exc)) from exc
        results = [t for t in response.get("results", []) if isinstance(t, dict)
                   and isinstance(t.get("video_id"), str)]
        self._search_cache = {t["video_id"]: t for t in results}
        return SearchMedia(result=[
            self._item(track, f"{MEDIA_PREFIX}{track['video_id']}")
            for track in results
        ])

    async def async_play_media(self, media_type, media_id, **kwargs):
        ident = str(media_id)
        if ident.startswith(QUEUE_PREFIX) or ident.startswith(HISTORY_PREFIX):
            location = QUEUE if ident.startswith(QUEUE_PREFIX) else HISTORY
            try:
                _, index, video_id = ident.split(":", 2)
                index = int(index)
            except (ValueError, TypeError) as err:
                raise BrowseError("Invalid queue selection") from err
            if len(video_id) != 11 or index < 0:
                raise BrowseError("Invalid song selection")
            await self.coordinator.command(
                "/api/queue/play" if location == QUEUE else "/api/history/play",
                {"index": index, "video_id": video_id}
            )
            return
        if ident.startswith(MEDIA_PREFIX):
            video_id = ident[len(MEDIA_PREFIX):]
            track = self._search_cache.get(video_id) or {}
            payload = {
                "video_id": video_id, "radio": True,
                "title": track.get("title", video_id),
                "artist": track.get("artist", ""),
                "duration_seconds": track.get("duration_seconds"),
                "thumbnail": track.get("thumbnail"),
            }
            await self.coordinator.command("/api/play", payload)
            return
        if ident.startswith(LIBRARY_PLAYLIST_PREFIX):
            await self.coordinator.command("/api/playlist", {
                "playlist_id": ident[len(LIBRARY_PLAYLIST_PREFIX):],
                "radio_after": False
            })
        elif media_type == MediaType.PLAYLIST:
            await self.coordinator.command("/api/playlist", {
                "playlist_id": ident, "radio_after": False
            })
        elif ident.startswith("id:"):
            await self.coordinator.command("/api/play", {
                "video_id": ident[3:], "radio": True
            })
        else:
            await self.coordinator.command("/api/play", {
                "query": ident, "radio": True
            })
