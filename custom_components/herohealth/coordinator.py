"""Data update coordinator for Hero Health."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import HeroHealthApiClient, HeroHealthApiError, HeroHealthAuthError
from .const import CONF_ACCOUNT_ID, CONF_REFRESH_TOKEN, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class HeroHealthCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Hero Health data update coordinator."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.config_entry = entry
        session = async_get_clientsession(hass)
        self.client = HeroHealthApiClient(
            session=session,
            refresh_token=entry.data[CONF_REFRESH_TOKEN],
            account_id=entry.data.get(CONF_ACCOUNT_ID),
        )

    def _persist_refresh_token(self) -> None:
        """Update the stored refresh token if it changed."""
        current = self.config_entry.data.get(CONF_REFRESH_TOKEN)
        if self.client.refresh_token != current:
            new_data = {**self.config_entry.data, CONF_REFRESH_TOKEN: self.client.refresh_token}
            self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            _LOGGER.debug("Updated stored refresh token")

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Hero Health API."""
        try:
            result = await self._fetch_all_data()
            # Persist refresh token if it was rotated
            self._persist_refresh_token()
            return result
        except HeroHealthAuthError as err:
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
        except HeroHealthApiError as err:
            if self.data:
                _LOGGER.warning(
                    "Error fetching Hero Health data (%s), keeping last known data",
                    err,
                )
                return self.data
            _LOGGER.error(
                "Error fetching Hero Health data with no previous data: %s", err
            )
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    async def _fetch_all_data(self) -> dict[str, Any]:
        """Fetch all data from the API concurrently."""
        # Fetch main data concurrently
        results = await asyncio.gather(
            self.client.get_home_screen_doses(),
            self.client.get_home_screen_events(),
            self.client.get_pills_by_schedules(),
            self.client.get_pill_stats(),
            self.client.get_stats(),
            self.client.check_device_offline(),
            self.client.get_device_config(),
            self.client.get_taken_slots(),
            return_exceptions=True,
        )

        # Unpack results, using defaults for any that failed
        home_doses = results[0] if not isinstance(results[0], Exception) else []
        home_events = results[1] if not isinstance(results[1], Exception) else []
        pills_by_schedule = results[2] if not isinstance(results[2], Exception) else []
        pill_stats = results[3] if not isinstance(results[3], Exception) else {}
        overall_stats = results[4] if not isinstance(results[4], Exception) else {}
        device_offline = results[5] if not isinstance(results[5], Exception) else {}
        device_config = results[6] if not isinstance(results[6], Exception) else {}
        taken_slots = results[7] if not isinstance(results[7], Exception) else []

        # Log any individual failures
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                _LOGGER.warning("API call %d failed: %s", i, result)

        # Check if ALL calls failed with auth error - re-raise to trigger re-auth
        auth_failures = [r for r in results if isinstance(r, HeroHealthAuthError)]
        if len(auth_failures) == len(results):
            raise auth_failures[0]

        # Normalize taken_slots to a list
        if isinstance(taken_slots, dict):
            taken_slots = taken_slots.get("slots", taken_slots.get("results", []))
        if not isinstance(taken_slots, list):
            taken_slots = []

        # Fetch remaining days for each occupied slot
        remaining_days: dict[int, dict[str, Any]] = {}
        for slot in taken_slots:
            slot_index = slot.get("slot_index") if isinstance(slot, dict) else None
            if slot_index is not None:
                try:
                    days_data = await self.client.get_pill_remaining_days(slot_index)
                    remaining_days[slot_index] = days_data
                except HeroHealthApiError as err:
                    _LOGGER.debug(
                        "Failed to get remaining days for slot %s: %s",
                        slot_index,
                        err,
                    )

        # Determine device online status
        device_online = True
        if isinstance(device_offline, dict):
            device_online = not device_offline.get("is_offline", not device_offline.get("online", True))

        data = {
            "home_doses": home_doses if isinstance(home_doses, list) else [],
            "home_events": home_events if isinstance(home_events, list) else [],
            "pills_by_schedule": pills_by_schedule if isinstance(pills_by_schedule, list) else [],
            "pill_stats": pill_stats if isinstance(pill_stats, (dict, list)) else {},
            "overall_stats": overall_stats if isinstance(overall_stats, dict) else {},
            "device_online": device_online,
            "device_config": device_config if isinstance(device_config, dict) else {},
            "taken_slots": taken_slots,
            "remaining_days": remaining_days,
        }

        _LOGGER.debug(
            "Hero Health update successful: %d doses, %d events, %d slots, device_online=%s",
            len(data["home_doses"]),
            len(data["home_events"]),
            len(data["taken_slots"]),
            data["device_online"],
        )

        return data
