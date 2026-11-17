"""Polling coordinator for the YouTube Music Live bridge."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiohttp import ClientError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import YTMusicAPIError, YTMusicAuthError, YTMusicClient
from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class YTMusicCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Share one API status poll among all entities."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: YTMusicClient) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, config_entry=entry, update_interval=SCAN_INTERVAL
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.client.status()
        except YTMusicAuthError as exc:
            raise ConfigEntryAuthFailed("API key rejected") from exc
        except (YTMusicAPIError, ClientError, asyncio.TimeoutError) as exc:
            raise UpdateFailed(f"YouTube Music Live status unavailable: {exc}") from exc

    async def async_command(self, endpoint: str, payload: dict | None = None) -> None:
        """Send a control command then immediately refresh the current state."""
        await self.client.command(endpoint, payload)
        await self.async_request_refresh()
