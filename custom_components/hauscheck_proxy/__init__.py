from __future__ import annotations

import json
import logging
from typing import Any

import voluptuous as vol
from aiohttp import ClientError, web

from homeassistant.components.http import HomeAssistantView
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .const import CONF_BASE_URL, CONF_TIMEOUT, DEFAULT_BASE_URL, DEFAULT_TIMEOUT, DOMAIN

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_BASE_URL, default=DEFAULT_BASE_URL): cv.string,
                vol.Required(CONF_TOKEN): cv.string,
                vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): cv.positive_int,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    domain_config = config.get(DOMAIN)
    if not domain_config:
        _LOGGER.warning("HausCheck Proxy ist nicht konfiguriert")
        return True

    base_url = str(domain_config.get(CONF_BASE_URL) or DEFAULT_BASE_URL).rstrip("/")
    token = str(domain_config.get(CONF_TOKEN) or "").strip()
    timeout = int(domain_config.get(CONF_TIMEOUT) or DEFAULT_TIMEOUT)

    if not token:
        _LOGGER.error("HausCheck Proxy benötigt token in configuration.yaml")
        return False

    hass.data[DOMAIN] = {
        CONF_BASE_URL: base_url,
        CONF_TOKEN: token,
        CONF_TIMEOUT: timeout,
    }

    hass.http.register_view(HausCheckHealthView())
    hass.http.register_view(HausCheckHousesView())
    hass.http.register_view(HausCheckHouseView())
    hass.http.register_view(HausCheckProfilesView())
    hass.http.register_view(HausCheckCandidatesView())
    hass.http.register_view(HausCheckMcpView())

    _LOGGER.info("HausCheck Proxy registriert: %s", base_url)
    return True


class HausCheckProxyView(HomeAssistantView):
    requires_auth = True

    async def _proxy(
        self,
        request: web.Request,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_data: Any | None = None,
    ) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        config = hass.data.get(DOMAIN)
        if not config:
            return self.json({"error": "HausCheck Proxy nicht konfiguriert"}, status_code=503)

        base_url = str(config[CONF_BASE_URL]).rstrip("/")
        token = str(config[CONF_TOKEN])
        timeout = int(config[CONF_TIMEOUT])
        url = f"{base_url}{path}"
        session = async_get_clientsession(hass)
        headers = {"Authorization": f"Bearer {token}"}

        try:
            async with session.request(
                method,
                url,
                params=params,
                json=json_data,
                headers=headers,
                timeout=timeout,
            ) as response:
                text = await response.text()
                content_type = response.headers.get("content-type", "")
                if "application/json" in content_type:
                    try:
                        data = json.loads(text) if text else {}
                    except json.JSONDecodeError:
                        data = {"raw": text}
                    return self.json(data, status_code=response.status)
                return web.Response(text=text, status=response.status, content_type=content_type or "text/plain")
        except TimeoutError:
            return self.json({"error": "Timeout beim Zugriff auf HausCheck Add-on"}, status_code=504)
        except ClientError as exc:
            return self.json({"error": f"HausCheck Add-on nicht erreichbar: {exc}"}, status_code=502)


class HausCheckHealthView(HausCheckProxyView):
    url = "/api/hauscheck/health"
    name = "api:hauscheck:health"

    async def get(self, request: web.Request) -> web.Response:
        return await self._proxy(request, "GET", "/api/chatgpt/health")


class HausCheckHousesView(HausCheckProxyView):
    url = "/api/hauscheck/houses"
    name = "api:hauscheck:houses"

    async def get(self, request: web.Request) -> web.Response:
        params = dict(request.query)
        return await self._proxy(request, "GET", "/api/chatgpt/houses", params=params)


class HausCheckHouseView(HausCheckProxyView):
    url = "/api/hauscheck/houses/{house_id}"
    name = "api:hauscheck:house"

    async def get(self, request: web.Request, house_id: str) -> web.Response:
        return await self._proxy(request, "GET", f"/api/chatgpt/houses/{house_id}")


class HausCheckProfilesView(HausCheckProxyView):
    url = "/api/hauscheck/search-profiles"
    name = "api:hauscheck:search_profiles"

    async def get(self, request: web.Request) -> web.Response:
        return await self._proxy(request, "GET", "/api/chatgpt/search-profiles")


class HausCheckCandidatesView(HausCheckProxyView):
    url = "/api/hauscheck/search-profiles/{profile_id}/candidates"
    name = "api:hauscheck:candidates"

    async def get(self, request: web.Request, profile_id: str) -> web.Response:
        params = dict(request.query)
        return await self._proxy(request, "GET", f"/api/chatgpt/search-profiles/{profile_id}/candidates", params=params)


class HausCheckMcpView(HausCheckProxyView):
    url = "/api/hauscheck/mcp"
    name = "api:hauscheck:mcp"

    async def get(self, request: web.Request) -> web.Response:
        return await self._proxy(request, "GET", "/mcp")

    async def post(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return self.json({"error": "Ungültiges JSON"}, status_code=400)
        return await self._proxy(request, "POST", "/mcp", json_data=payload)
