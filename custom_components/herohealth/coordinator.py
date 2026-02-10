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
from .const import CONF_REFRESH_TOKEN, DEFAULT_SCAN_INTERVAL, DOMAIN

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
        results = await asyncio.gather(
            self.client.get_home_screen_doses(),
            self.client.get_home_screen_events(),
            self.client.get_pills_by_schedules(),
            self.client.get_device_config(),
            self.client.get_taken_slots(),
            return_exceptions=True,
        )

        raw_doses = results[0] if not isinstance(results[0], Exception) else {}
        raw_events = results[1] if not isinstance(results[1], Exception) else {}
        pills_by_schedule = results[2] if not isinstance(results[2], Exception) else {}
        device_config = results[3] if not isinstance(results[3], Exception) else {}
        raw_taken_slots = results[4] if not isinstance(results[4], Exception) else {}

        # Log any individual failures
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                _LOGGER.warning("API call %d failed: %s", i, result)

        # Check if ALL calls failed with auth error — re-raise to trigger re-auth
        auth_failures = [r for r in results if isinstance(r, HeroHealthAuthError)]
        if len(auth_failures) == len(results):
            raise auth_failures[0]

        # Flatten doses from nested dates[].times[].doses[] structure
        doses: list[dict[str, Any]] = []
        if isinstance(raw_doses, dict):
            for date_entry in raw_doses.get("dates", []):
                if not isinstance(date_entry, dict):
                    continue
                for time_entry in date_entry.get("times", []):
                    if not isinstance(time_entry, dict):
                        continue
                    scheduled_dt = time_entry.get("scheduled_datetime")
                    for dose in time_entry.get("doses", []):
                        if isinstance(dose, dict):
                            dose["scheduled_datetime"] = scheduled_dt
                            doses.append(dose)

        # Flatten events from {today: [...], yesterday: [...]} structure
        events: list[dict[str, Any]] = []
        if isinstance(raw_events, dict):
            for day_events in raw_events.values():
                if isinstance(day_events, list):
                    for event in day_events:
                        if isinstance(event, dict):
                            events.append(event)

        # Normalize device_config
        if not isinstance(device_config, dict):
            device_config = {}

        # Build pill name map from device_config
        pill_map: dict[int, dict[str, Any]] = {}
        for pill in device_config.get("pills", []):
            if isinstance(pill, dict) and pill.get("slot") is not None:
                pill_map[pill["slot"]] = pill

        # Normalize taken_slots: API returns {"slots": [1, 2, 3, ...]}
        slot_numbers: list[int] = []
        if isinstance(raw_taken_slots, dict):
            slot_numbers = raw_taken_slots.get("slots", [])
        elif isinstance(raw_taken_slots, list):
            slot_numbers = raw_taken_slots

        # Enrich slots with pill names from device_config
        taken_slots: list[dict[str, Any]] = []
        for slot_num in slot_numbers:
            if not isinstance(slot_num, int):
                continue
            pill_info = pill_map.get(slot_num, {})
            taken_slots.append({
                "slot_index": slot_num,
                "pill_name": pill_info.get("name"),
                "stored_in_hero": pill_info.get("stored_in_hero"),
            })

        # Fetch remaining days for each occupied slot
        remaining_days: dict[int, dict[str, Any]] = {}
        for slot_info in taken_slots:
            slot_index = slot_info["slot_index"]
            try:
                days_data = await self.client.get_pill_remaining_days(slot_index)
                remaining_days[slot_index] = days_data
            except HeroHealthApiError as err:
                _LOGGER.debug(
                    "Failed to get remaining days for slot %s: %s",
                    slot_index,
                    err,
                )

        data = {
            "doses": doses,
            "events": events,
            "pills_by_schedule": pills_by_schedule,
            "device_config": device_config,
            "taken_slots": taken_slots,
            "remaining_days": remaining_days,
            "pill_map": pill_map,
        }

        _LOGGER.debug(
            "Hero Health update: %d doses, %d events, %d slots",
            len(doses),
            len(events),
            len(taken_slots),
        )

        return data
