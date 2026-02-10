"""Hero Health API client.

Authentication uses OAuth2 tokens obtained via the Authorization Code flow
with PKCE against id.herohealth.com. Token refresh uses the OAuth2 token
endpoint on id.herohealth.com.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import aiohttp

from .const import (
    BASE_URL,
    HERO_CLIENT_HEADER,
    OAUTH_CLIENT_ID,
    OAUTH_TOKEN_URL,
    TOKEN_LIFETIME_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


class HeroHealthApiError(Exception):
    """Base exception for Hero Health API errors."""


class HeroHealthAuthError(HeroHealthApiError):
    """Authentication error."""


class HeroHealthConnectionError(HeroHealthApiError):
    """Connection error."""


class HeroHealthApiClient:
    """Hero Health API client."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        refresh_token: str,
        account_id: str | None = None,
    ) -> None:
        """Initialize the API client."""
        self._session = session
        self._access_token: str | None = None
        self._refresh_token: str = refresh_token
        self._account_id: str | None = account_id
        self._token_acquired_at: float = 0

    @property
    def refresh_token(self) -> str:
        """Return the current refresh token (may be updated after refresh)."""
        return self._refresh_token

    def _get_headers(self) -> dict[str, str]:
        """Get headers for authenticated API requests."""
        headers = {
            "Accept": "application/json",
            "X-Hero-Client": HERO_CLIENT_HEADER,
        }
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        if self._account_id:
            headers["X-Hero-Account"] = self._account_id
        return headers

    def _token_is_expired(self) -> bool:
        """Check if the token is expired or near expiry (2 min buffer)."""
        if not self._access_token or self._token_acquired_at == 0:
            return True
        elapsed = time.monotonic() - self._token_acquired_at
        return elapsed >= (TOKEN_LIFETIME_SECONDS - 120)

    async def refresh_access_token(self) -> dict[str, Any]:
        """Refresh the access token via the OAuth2 endpoint on id.herohealth.com."""
        _LOGGER.debug("Refreshing access token")

        try:
            async with self._session.post(
                OAUTH_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": OAUTH_CLIENT_ID,
                    "refresh_token": self._refresh_token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as response:
                if response.status in (400, 401):
                    text = await response.text()
                    _LOGGER.debug(
                        "OAuth refresh rejected: status %s, body: %s",
                        response.status,
                        text[:500],
                    )
                    raise HeroHealthAuthError(
                        "Token refresh failed - refresh token may be expired"
                    )
                if response.status != 200:
                    text = await response.text()
                    _LOGGER.debug(
                        "OAuth refresh failed: status %s, body: %s",
                        response.status,
                        text[:500],
                    )
                    raise HeroHealthApiError(
                        f"Token refresh failed: {response.status}"
                    )
                data = await response.json()
        except aiohttp.ClientError as err:
            raise HeroHealthConnectionError(f"Connection error: {err}") from err

        self._access_token = data.get("access_token")
        new_refresh = data.get("refresh_token")
        if new_refresh:
            self._refresh_token = new_refresh
        self._token_acquired_at = time.monotonic()

        if not self._access_token:
            _LOGGER.error(
                "No access_token in refresh response: %s",
                list(data.keys()) if isinstance(data, dict) else data,
            )
            raise HeroHealthAuthError("No access token in refresh response")

        _LOGGER.debug("Token refresh successful")
        return data

    async def _ensure_token(self) -> None:
        """Ensure we have a valid token, refreshing as needed."""
        if not self._access_token or self._token_is_expired():
            await self.refresh_access_token()

    async def _request(
        self, method: str, path: str, **kwargs: Any
    ) -> Any:
        """Make an authenticated API request with automatic token management."""
        await self._ensure_token()

        url = f"{BASE_URL}{path}"
        _LOGGER.debug("API request: %s %s", method, url)

        try:
            async with self._session.request(
                method, url, headers=self._get_headers(), **kwargs
            ) as response:
                if response.status == 401:
                    _LOGGER.debug("Got 401, refreshing token and retrying")
                    await self.refresh_access_token()
                    # Retry once
                    async with self._session.request(
                        method, url, headers=self._get_headers(), **kwargs
                    ) as retry_response:
                        if retry_response.status == 401:
                            raise HeroHealthAuthError(
                                "Authentication failed after retry"
                            )
                        if retry_response.status != 200:
                            text = await retry_response.text()
                            _LOGGER.debug(
                                "Retry failed: %s, body: %s",
                                retry_response.status,
                                text[:500],
                            )
                            raise HeroHealthApiError(
                                f"Request failed: {retry_response.status}"
                            )
                        return await retry_response.json()

                if response.status != 200:
                    text = await response.text()
                    _LOGGER.debug(
                        "Request failed: %s %s -> %s, body: %s",
                        method,
                        url,
                        response.status,
                        text[:500],
                    )
                    raise HeroHealthApiError(
                        f"Request failed: {method} {path} -> {response.status}"
                    )
                return await response.json()
        except aiohttp.ClientError as err:
            raise HeroHealthConnectionError(f"Connection error: {err}") from err

    # ---- Data fetching methods ----

    async def get_user_details(self) -> dict[str, Any]:
        """Get user details."""
        return await self._request("GET", "/frontend/user-details/")

    async def get_home_screen_doses(self) -> Any:
        """Get current doses for home screen display."""
        return await self._request("GET", "/frontend/home-screen-doses/")

    async def get_home_screen_events(self) -> Any:
        """Get recent events for home screen display."""
        return await self._request("GET", "/frontend/get-home-screen-events/")

    async def get_pills_by_schedules(self) -> Any:
        """Get pills organized by schedule."""
        return await self._request("GET", "/frontend/pills-by-schedules/")

    async def get_pill_stats(self) -> Any:
        """Get pill statistics."""
        return await self._request("GET", "/frontend/pill-stats/")

    async def get_stats(self) -> Any:
        """Get overall adherence statistics."""
        return await self._request("GET", "/frontend/stats/")

    async def check_device_offline(self) -> dict[str, Any]:
        """Check if the Hero device is offline."""
        return await self._request("POST", "/frontend/check-hero-offline/")

    async def get_device_config(self) -> dict[str, Any]:
        """Get device configuration."""
        return await self._request("GET", "/frontend/device-config-get/")

    async def get_taken_slots(self) -> Any:
        """Get which medication slots are occupied."""
        return await self._request("GET", "/frontend/get-taken-slots/")

    async def get_pill_remaining_days(self, slot_index: int) -> dict[str, Any]:
        """Get remaining days for a specific medication slot."""
        return await self._request(
            "GET", f"/frontend/pill-remaining-days/?slot_index={slot_index}"
        )

    async def get_owner_details(self) -> dict[str, Any]:
        """Get owner details."""
        return await self._request("GET", "/frontend/owner-details/")

    async def get_activity_log_device(self) -> Any:
        """Get device activity log."""
        return await self._request("GET", "/frontend/activity-log-device/")

    async def get_current_config(self) -> Any:
        """Get current medication configuration."""
        return await self._request("GET", "/frontend/user-config-current")

    async def get_safety_settings(self) -> dict[str, Any]:
        """Get safety settings."""
        return await self._request("GET", "/frontend/safety-settings-read/")

    async def get_vacation_config(self) -> dict[str, Any]:
        """Get vacation mode configuration."""
        return await self._request("GET", "/frontend/vacation-get-config/")
