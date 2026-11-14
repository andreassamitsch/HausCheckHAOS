"""User-configurable bridge URL and local API key."""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

import voluptuous as vol
from aiohttp import ClientError

from homeassistant import config_entries
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import YTMusicAPIError, YTMusicAuthError, YTMusicClient
from .const import CONF_API_KEY, DEFAULT_URL, DOMAIN


class YTMusicFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure the existing local music app."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None):
        errors = {}
        if user_input is not None:
            url = str(user_input["url"]).strip().rstrip("/")
            parsed = urlsplit(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
                errors["base"] = "invalid_url"
            else:
                try:
                    client = YTMusicClient(
                        async_get_clientsession(self.hass), url, user_input[CONF_API_KEY]
                    )
                    status = await client.status()
                    if "queue" not in status or "radio_enabled" not in status:
                        errors["base"] = "invalid_response"
                except YTMusicAuthError:
                    errors["base"] = "invalid_auth"
                except (YTMusicAPIError, ClientError, asyncio.TimeoutError, OSError):
                    errors["base"] = "cannot_connect"
                else:
                    if not errors:
                        await self.async_set_unique_id(url.lower())
                        self._abort_if_unique_id_configured()
                        return self.async_create_entry(
                            title="YouTube Music Live",
                            data={"url": url, CONF_API_KEY: user_input[CONF_API_KEY]},
                        )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("url", default=DEFAULT_URL): str,
                    vol.Required(CONF_API_KEY): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )
