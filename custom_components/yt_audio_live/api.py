"""Async local API client for the YouTube Music Live app."""

from __future__ import annotations

from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout


class YTMusicAPIError(Exception):
    """The local YouTube Music Live API returned an error."""


class YTMusicAuthError(YTMusicAPIError):
    """The API key was rejected."""


class YTMusicClient:
    """Communicate with the existing app; never adjust soundbar volume."""

    def __init__(self, session: ClientSession, url: str, api_key: str) -> None:
        self._session = session
        self._url = url.rstrip("/")
        self._headers = {"X-API-Key": api_key}

    async def request(self, method: str, path: str, payload: dict | None = None) -> dict[str, Any]:
        """Issue a documented API request, keeping credentials out of logs."""
        async with self._session.request(
            method,
            f"{self._url}{path}",
            headers=self._headers,
            json=payload,
            timeout=ClientTimeout(total=12),
        ) as response:
            if response.status == 401:
                raise YTMusicAuthError("API-Schlüssel ungültig")
            if response.status >= 400:
                raise YTMusicAPIError(f"API request failed with HTTP {response.status}")
            try:
                result = await response.json()
            except (ValueError, ClientError) as exc:
                raise YTMusicAPIError("API returned invalid JSON") from exc
            if not isinstance(result, dict):
                raise YTMusicAPIError("API returned a non-object response")
            return result

    async def status(self) -> dict[str, Any]:
        """Fetch title, queue and radio state."""
        return await self.request("GET", "/api/status")

    async def command(self, endpoint: str, payload: dict | None = None) -> dict[str, Any]:
        """Call a supported write endpoint."""
        return await self.request("POST", endpoint, payload or {})
