"""Queue length plus readable track metadata."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import YTMusicEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([YTMusicQueue(entry.runtime_data)])


class YTMusicQueue(YTMusicEntity, SensorEntity):
    """Queue count; individual tracks are available as attributes."""

    _attr_name = "Warteschlange"
    _attr_icon = "mdi:playlist-music"
    _attr_native_unit_of_measurement = "Titel"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "queue")

    @property
    def native_value(self) -> int:
        return int(self.coordinator.data.get("queue_length", 0))

    @property
    def extra_state_attributes(self) -> dict:
        tracks = self.coordinator.data.get("queue") or []
        return {
            "tracks": [
                {
                    "title": track.get("title"),
                    "artist": track.get("artist"),
                    "video_id": track.get("video_id"),
                }
                for track in tracks[:50]
            ],
            "next_title": tracks[0].get("title") if tracks else None,
            "radio_prefetching": bool(
                self.coordinator.data.get("radio_prefetching", False)
            ),
        }
