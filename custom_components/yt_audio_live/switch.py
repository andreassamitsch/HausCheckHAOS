"""Radio/autoplay toggle via the existing music app API."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import YTMusicEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([YTMusicRadio(entry.runtime_data)])


class YTMusicRadio(YTMusicEntity, SwitchEntity):
    """Control the app's automatic follow-up track selection."""

    _attr_name = "Radio"
    _attr_icon = "mdi:radio"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "radio")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("radio_enabled", False))

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_command("/api/radio", {"enabled": True})

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_command("/api/radio", {"enabled": False})
