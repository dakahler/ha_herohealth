"""Sensor platform for Hero Health."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import HeroHealthCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hero Health sensors from a config entry."""
    coordinator: HeroHealthCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = [
        HeroHealthNextDoseSensor(coordinator, entry),
        HeroHealthLastEventSensor(coordinator, entry),
        HeroHealthDosesTakenTodaySensor(coordinator, entry),
    ]

    # Create dynamic per-pill remaining-days sensors
    taken_slots = coordinator.data.get("taken_slots", []) if coordinator.data else []
    for slot in taken_slots:
        if not isinstance(slot, dict):
            continue
        slot_index = slot.get("slot_index")
        pill_name = slot.get("pill_name") or f"Slot {slot_index}"
        if slot_index is not None:
            entities.append(
                HeroHealthPillRemainingDaysSensor(
                    coordinator, entry, slot_index, pill_name
                )
            )

    async_add_entities(entities)


class HeroHealthBaseSensor(CoordinatorEntity[HeroHealthCoordinator], SensorEntity):
    """Base class for Hero Health sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HeroHealthCoordinator,
        entry: ConfigEntry,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Hero Health Dispenser",
            manufacturer="Hero Health",
            entry_type=DeviceEntryType.SERVICE,
        )

    @staticmethod
    def _parse_datetime(time_str: str | None) -> datetime | None:
        """Parse a datetime string and ensure it is timezone-aware."""
        if not time_str:
            return None
        try:
            dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
            return dt
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def _dose_is_taken(dose: dict[str, Any]) -> bool:
        """Check if a dose state indicates it was taken."""
        state = dose.get("state", "")
        return state.startswith("taken")

    @staticmethod
    def _dose_is_done(dose: dict[str, Any]) -> bool:
        """Check if a dose state indicates it is no longer pending."""
        state = dose.get("state", "")
        return state.startswith("taken") or state in ("missed", "skipped")

    @staticmethod
    def _get_pill_names(dose: dict[str, Any]) -> list[str]:
        """Extract pill names from a dose's pills array."""
        names = []
        pills = dose.get("pills", [])
        if not isinstance(pills, list):
            return names
        for pill_entry in pills:
            if not isinstance(pill_entry, dict):
                continue
            # Pills are nested: {"pill": {"name": "..."}, "scheduled_pill_qty": ...}
            pill_obj = pill_entry.get("pill", {})
            if isinstance(pill_obj, dict):
                name = pill_obj.get("name")
                if name:
                    names.append(name)
            else:
                # Fallback for flat structure
                name = pill_entry.get("name") or pill_entry.get("drug_name")
                if name:
                    names.append(name)
        return names


class HeroHealthNextDoseSensor(HeroHealthBaseSensor):
    """Sensor for the next scheduled dose time."""

    def __init__(
        self, coordinator: HeroHealthCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="next_dose",
                name="Next Dose",
                device_class=SensorDeviceClass.TIMESTAMP,
                icon="mdi:pill",
            ),
        )

    @property
    def native_value(self) -> datetime | None:
        """Return the time of the next pending dose."""
        if self.coordinator.data is None:
            return None

        doses = self.coordinator.data.get("doses", [])
        now = dt_util.now()
        next_time: datetime | None = None

        for dose in doses:
            if not isinstance(dose, dict):
                continue
            if self._dose_is_done(dose):
                continue

            dose_time = self._parse_datetime(dose.get("scheduled_datetime"))
            if dose_time and dose_time > now:
                if next_time is None or dose_time < next_time:
                    next_time = dose_time

        return next_time

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        if self.coordinator.data is None:
            return {}

        doses = self.coordinator.data.get("doses", [])
        now = dt_util.now()
        next_dose: dict[str, Any] | None = None
        next_time: datetime | None = None

        for dose in doses:
            if not isinstance(dose, dict):
                continue
            if self._dose_is_done(dose):
                continue

            dose_time = self._parse_datetime(dose.get("scheduled_datetime"))
            if dose_time and dose_time > now:
                if next_time is None or dose_time < next_time:
                    next_time = dose_time
                    next_dose = dose

        if not next_dose:
            return {}

        pill_names = self._get_pill_names(next_dose)
        return {
            "pills": ", ".join(pill_names) if pill_names else None,
            "pill_count": len(pill_names),
        }


class HeroHealthLastEventSensor(HeroHealthBaseSensor):
    """Sensor for the most recent device event."""

    def __init__(
        self, coordinator: HeroHealthCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="last_event",
                name="Last Event",
                device_class=SensorDeviceClass.TIMESTAMP,
                icon="mdi:history",
            ),
        )

    @property
    def native_value(self) -> datetime | None:
        """Return the timestamp of the most recent event."""
        if self.coordinator.data is None:
            return None

        events = self.coordinator.data.get("events", [])
        if not events:
            return None

        latest_time: datetime | None = None
        for event in events:
            if not isinstance(event, dict):
                continue
            time_str = event.get("actual_datetime") or event.get("scheduled_datetime")
            event_time = self._parse_datetime(time_str)
            if event_time:
                if latest_time is None or event_time > latest_time:
                    latest_time = event_time

        return latest_time

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        if self.coordinator.data is None:
            return {}

        events = self.coordinator.data.get("events", [])
        if not events:
            return {}

        latest_event: dict[str, Any] | None = None
        latest_time: datetime | None = None
        for event in events:
            if not isinstance(event, dict):
                continue
            time_str = event.get("actual_datetime") or event.get("scheduled_datetime")
            event_time = self._parse_datetime(time_str)
            if event_time:
                if latest_time is None or event_time > latest_time:
                    latest_time = event_time
                    latest_event = event

        if not latest_event:
            return {}

        # Event pills are flat: [{"name": "...", "dosage": "..."}]
        pill_names = []
        for pill in latest_event.get("pills", []):
            if isinstance(pill, dict):
                name = pill.get("name")
                if name:
                    pill_names.append(name)

        return {
            "status": latest_event.get("status"),
            "pill_source": latest_event.get("pill_source"),
            "pills": ", ".join(pill_names) if pill_names else None,
        }


class HeroHealthDosesTakenTodaySensor(HeroHealthBaseSensor):
    """Sensor for the number of doses taken today."""

    def __init__(
        self, coordinator: HeroHealthCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="doses_taken_today",
                name="Doses Taken Today",
                icon="mdi:checkbox-marked-circle-outline",
                state_class=SensorStateClass.TOTAL,
            ),
        )

    @property
    def native_value(self) -> int | None:
        """Return the count of doses taken today."""
        if self.coordinator.data is None:
            return None

        doses = self.coordinator.data.get("doses", [])
        today = dt_util.now().date()
        taken = 0

        for dose in doses:
            if not isinstance(dose, dict):
                continue
            if not self._dose_is_taken(dose):
                continue
            time_str = (
                dose.get("dispensed_datetime")
                or dose.get("scheduled_datetime")
            )
            dose_time = self._parse_datetime(time_str)
            if dose_time and dose_time.date() == today:
                taken += 1

        return taken

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        if self.coordinator.data is None:
            return {}

        doses = self.coordinator.data.get("doses", [])
        today = dt_util.now().date()
        total = 0
        missed = 0
        pending = 0

        for dose in doses:
            if not isinstance(dose, dict):
                continue
            time_str = (
                dose.get("dispensed_datetime")
                or dose.get("scheduled_datetime")
            )
            dose_time = self._parse_datetime(time_str)
            if not dose_time or dose_time.date() != today:
                continue

            total += 1
            state = dose.get("state", "")
            if state == "missed":
                missed += 1
            elif not self._dose_is_done(dose):
                pending += 1

        return {
            "total_doses_today": total,
            "missed_today": missed,
            "pending_today": pending,
        }


class HeroHealthPillRemainingDaysSensor(
    CoordinatorEntity[HeroHealthCoordinator], SensorEntity
):
    """Sensor for remaining days of a specific medication."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HeroHealthCoordinator,
        entry: ConfigEntry,
        slot_index: int,
        pill_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._slot_index = slot_index
        self._pill_name = pill_name
        self.entity_description = SensorEntityDescription(
            key=f"pill_remaining_days_{slot_index}",
            name=f"{pill_name} Remaining Days",
            icon="mdi:calendar-clock",
            native_unit_of_measurement="days",
            state_class=SensorStateClass.MEASUREMENT,
        )
        self._attr_unique_id = (
            f"{entry.entry_id}_pill_remaining_days_{slot_index}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Hero Health Dispenser",
            manufacturer="Hero Health",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> int | None:
        """Return the remaining days for this pill."""
        if self.coordinator.data is None:
            return None

        remaining = self.coordinator.data.get("remaining_days", {})
        slot_data = remaining.get(self._slot_index, {})
        if not isinstance(slot_data, dict):
            return None

        # API returns {"exact": N, "min": N, "max": N, "error": ...}
        days = slot_data.get("exact") or slot_data.get("min")
        if days is not None:
            try:
                return int(days)
            except (ValueError, TypeError):
                return None
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        if self.coordinator.data is None:
            return {}

        remaining = self.coordinator.data.get("remaining_days", {})
        slot_data = remaining.get(self._slot_index, {})
        if not isinstance(slot_data, dict):
            return {}

        return {
            "slot_index": self._slot_index,
            "pill_name": self._pill_name,
            "days_min": slot_data.get("min"),
            "days_max": slot_data.get("max"),
            "pill_count_exact": slot_data.get("pill_count_exact"),
            "error": slot_data.get("error"),
        }
