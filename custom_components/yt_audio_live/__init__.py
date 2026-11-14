"""Home Assistant integration for the local YouTube Music Live app."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import YTMusicClient
from .const import CONF_API_KEY
from .coordinator import YTMusicCoordinator

PLATFORMS = (Platform.MEDIA_PLAYER, Platform.SENSOR, Platform.SWITCH)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Load the bridge without restarting or modifying the music app."""
    session = async_get_clientsession(hass)
    client = YTMusicClient(session, entry.data["url"], entry.data[CONF_API_KEY])
    coordinator = YTMusicCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the entities cleanly."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
