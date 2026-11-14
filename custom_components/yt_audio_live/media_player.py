"""Virtual media player for the app queue, not a second volume controller."""

from __future__ import annotations

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.components.media_player.const import MediaType
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import YTMusicEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create a single logical player for the app."""
    async_add_entities([YTMusicPlayer(entry.runtime_data)])


class YTMusicPlayer(YTMusicEntity, MediaPlayerEntity):
    """Expose play/pause/next and play_media via existing app endpoints."""

    _attr_name = None
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.PLAY_MEDIA
    )
    _attr_icon = "mdi:youtube-music"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "player")

    @property
    def state(self) -> MediaPlayerState:
        if not self.coordinator.data:
            return MediaPlayerState.IDLE
        status = self.coordinator.data
        cast = status.get("cast_state")
        if cast == "playing":
            return MediaPlayerState.PLAYING
        if cast == "paused":
            return MediaPlayerState.PAUSED
        if status.get("current"):
            return MediaPlayerState.IDLE
        return MediaPlayerState.OFF

    @property
    def media_title(self) -> str | None:
        return (self.coordinator.data.get("current") or {}).get("title")

    @property
    def media_artist(self) -> str | None:
        return (self.coordinator.data.get("current") or {}).get("artist")

    @property
    def media_duration(self) -> int | None:
        return (self.coordinator.data.get("current") or {}).get("duration_seconds")

    @property
    def media_content_id(self) -> str | None:
        return (self.coordinator.data.get("current") or {}).get("video_id")

    @property
    def media_content_type(self) -> str | None:
        return MediaType.MUSIC if self.media_content_id else None

    @property
    def extra_state_attributes(self) -> dict:
        status = self.coordinator.data
        return {
            "player_entity": status.get("player_entity"),
            "radio_enabled": status.get("radio_enabled", False),
            "queue_length": status.get("queue_length", 0),
            "last_error": status.get("last_error"),
        }

    async def async_media_play(self) -> None:
        await self.coordinator.async_command("/api/resume")

    async def async_media_pause(self) -> None:
        await self.coordinator.async_command("/api/pause")

    async def async_media_stop(self) -> None:
        await self.coordinator.async_command("/api/stop")

    async def async_media_next_track(self) -> None:
        await self.coordinator.async_command("/api/next")

    async def async_play_media(self, media_type: str, media_id: str, **kwargs) -> None:
        """Play search text, an exact video ID, or a playlist.

        Existing queue/radio is replaced only when a new selection starts.
        The volume of the physical soundbar is never changed.
        """
        if media_type in ("music", MediaType.MUSIC):
            payload = {"query": media_id, "radio": True}
            path = "/api/play"
        elif media_type in ("video", "youtube_id"):
            payload = {"video_id": media_id, "radio": True}
            path = "/api/play"
        elif media_type == "playlist":
            payload = {"playlist_id": media_id, "radio_after": True}
            path = "/api/playlist"
        else:
            raise ValueError("Use media type music, youtube_id, or playlist")
        await self.coordinator.async_command(path, payload)
