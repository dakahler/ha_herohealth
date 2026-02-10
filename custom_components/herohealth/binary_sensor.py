"""Binary sensor platform for Hero Health."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HeroHealthCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hero Health binary sensors from a config entry."""
    coordinator: HeroHealthCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([HeroHealthDeviceOnlineSensor(coordinator, entry)])


class HeroHealthDeviceOnlineSensor(
    CoordinatorEntity[HeroHealthCoordinator], BinarySensorEntity
):
    """Binary sensor for Hero Health device online status.

    Derived from whether the coordinator can successfully reach the API
    and return data (the check-hero-offline endpoint is unavailable).
    """

    _attr_has_entity_name = True
    entity_description = BinarySensorEntityDescription(
        key="device_online",
        name="Device Online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    )

    def __init__(
        self, coordinator: HeroHealthCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_device_online"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Hero Health Dispenser",
            manufacturer="Hero Health",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if the coordinator has data (API reachable)."""
        return self.coordinator.data is not None

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Return additional attributes."""
        if self.coordinator.data is None:
            return {}
        config = self.coordinator.data.get("device_config", {})
        return {
            "timezone_offset": config.get("timezone_offset"),
            "travel_mode": config.get("travel_mode"),
        }
