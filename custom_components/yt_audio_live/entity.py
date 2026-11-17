"""Shared device metadata for the bridge entities."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import YTMusicCoordinator


class YTMusicEntity(CoordinatorEntity[YTMusicCoordinator]):
    """Represents the local app, not the physical soundbar."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: YTMusicCoordinator, suffix: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"yt_audio_live_{suffix}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, "bridge")},
            name="YouTube Music Live",
            manufacturer="HausCheck",
            model="Local music bridge",
        )
