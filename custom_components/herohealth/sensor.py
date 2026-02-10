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
        HeroHealthAdherenceSensor(coordinator, entry),
        HeroHealthLastEventSensor(coordinator, entry),
        HeroHealthDosesTakenTodaySensor(coordinator, entry),
    ]

    # Create dynamic per-pill remaining-days sensors
    taken_slots = coordinator.data.get("taken_slots", []) if coordinator.data else []
    for slot in taken_slots:
        if not isinstance(slot, dict):
            continue
        slot_index = slot.get("slot_index")
        pill_name = (
            slot.get("pill_name")
            or slot.get("name")
            or slot.get("drug_name")
            or f"Slot {slot_index}"
        )
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
            model=coordinator.data.get("device_config", {}).get("model", "Hero")
            if coordinator.data
            else "Hero",
            sw_version=coordinator.data.get("device_config", {}).get(
                "firmware_version"
            )
            if coordinator.data
            else None,
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

        doses = self.coordinator.data.get("home_doses", [])
        now = dt_util.now()
        next_time: datetime | None = None

        for dose in doses:
            if not isinstance(dose, dict):
                continue
            status = dose.get("status", "").lower()
            if status in ("taken", "missed", "skipped"):
                continue

            time_str = (
                dose.get("scheduled_time")
                or dose.get("time")
                or dose.get("schedule_time")
            )
            dose_time = self._parse_datetime(time_str)
            if dose_time and dose_time > now:
                if next_time is None or dose_time < next_time:
                    next_time = dose_time

        return next_time

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        if self.coordinator.data is None:
            return {}

        doses = self.coordinator.data.get("home_doses", [])
        now = dt_util.now()
        next_dose: dict[str, Any] | None = None
        next_time: datetime | None = None

        for dose in doses:
            if not isinstance(dose, dict):
                continue
            status = dose.get("status", "").lower()
            if status in ("taken", "missed", "skipped"):
                continue

            time_str = (
                dose.get("scheduled_time")
                or dose.get("time")
                or dose.get("schedule_time")
            )
            dose_time = self._parse_datetime(time_str)
            if dose_time and dose_time > now:
                if next_time is None or dose_time < next_time:
                    next_time = dose_time
                    next_dose = dose

        if not next_dose:
            return {}

        pills = next_dose.get("pills", [])
        pill_names = []
        for pill in pills if isinstance(pills, list) else []:
            name = pill.get("name") or pill.get("drug_name") or pill.get("pill_name")
            if name:
                pill_names.append(name)

        return {
            "pills": ", ".join(pill_names) if pill_names else None,
            "pill_count": len(pills) if isinstance(pills, list) else 0,
        }


class HeroHealthAdherenceSensor(HeroHealthBaseSensor):
    """Sensor for overall medication adherence percentage."""

    def __init__(
        self, coordinator: HeroHealthCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator,
            entry,
            SensorEntityDescription(
                key="adherence",
                name="Medication Adherence",
                icon="mdi:chart-arc",
                native_unit_of_measurement="%",
                state_class=SensorStateClass.MEASUREMENT,
            ),
        )

    @property
    def native_value(self) -> float | None:
        """Return the adherence percentage."""
        if self.coordinator.data is None:
            return None

        stats = self.coordinator.data.get("overall_stats", {})
        if not isinstance(stats, dict):
            return None

        # Try various possible field names
        adherence = (
            stats.get("adherence_percentage")
            or stats.get("adherence")
            or stats.get("adherence_rate")
            or stats.get("percentage")
        )

        if adherence is not None:
            try:
                return round(float(adherence), 1)
            except (ValueError, TypeError):
                return None

        # Calculate from taken/total if available
        taken = stats.get("taken_count") or stats.get("taken") or 0
        total = stats.get("total_count") or stats.get("total") or 0
        if total > 0:
            return round(float(taken) / float(total) * 100, 1)

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        if self.coordinator.data is None:
            return {}

        stats = self.coordinator.data.get("overall_stats", {})
        if not isinstance(stats, dict):
            return {}

        return {
            "taken_count": stats.get("taken_count") or stats.get("taken"),
            "missed_count": stats.get("missed_count") or stats.get("missed"),
            "total_count": stats.get("total_count") or stats.get("total"),
            "period": stats.get("period"),
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

        events = self.coordinator.data.get("home_events", [])
        if not events or not isinstance(events, list):
            return None

        latest_time: datetime | None = None
        for event in events:
            if not isinstance(event, dict):
                continue
            time_str = (
                event.get("timestamp")
                or event.get("time")
                or event.get("created_at")
                or event.get("event_time")
            )
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

        events = self.coordinator.data.get("home_events", [])
        if not events or not isinstance(events, list):
            return {}

        # Find the most recent event
        latest_event: dict[str, Any] | None = None
        latest_time: datetime | None = None
        for event in events:
            if not isinstance(event, dict):
                continue
            time_str = (
                event.get("timestamp")
                or event.get("time")
                or event.get("created_at")
                or event.get("event_time")
            )
            event_time = self._parse_datetime(time_str)
            if event_time:
                if latest_time is None or event_time > latest_time:
                    latest_time = event_time
                    latest_event = event

        if not latest_event:
            return {}

        event_type = (
            latest_event.get("event_type")
            or latest_event.get("type")
            or latest_event.get("action")
        )
        details = (
            latest_event.get("details")
            or latest_event.get("description")
            or latest_event.get("message")
        )

        pills = latest_event.get("pills", [])
        pill_names = []
        for pill in pills if isinstance(pills, list) else []:
            name = pill.get("name") or pill.get("drug_name") or pill.get("pill_name")
            if name:
                pill_names.append(name)

        return {
            "event_type": event_type,
            "details": details,
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

        doses = self.coordinator.data.get("home_doses", [])
        today = dt_util.now().date()
        taken = 0

        for dose in doses:
            if not isinstance(dose, dict):
                continue
            status = dose.get("status", "").lower()
            if status != "taken":
                continue
            time_str = (
                dose.get("scheduled_time")
                or dose.get("time")
                or dose.get("schedule_time")
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

        doses = self.coordinator.data.get("home_doses", [])
        today = dt_util.now().date()
        total = 0
        missed = 0
        pending = 0

        for dose in doses:
            if not isinstance(dose, dict):
                continue
            time_str = (
                dose.get("scheduled_time")
                or dose.get("time")
                or dose.get("schedule_time")
            )
            dose_time = self._parse_datetime(time_str)
            if not dose_time or dose_time.date() != today:
                continue

            total += 1
            status = dose.get("status", "").lower()
            if status == "missed":
                missed += 1
            elif status not in ("taken", "skipped"):
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
            model=coordinator.data.get("device_config", {}).get("model", "Hero")
            if coordinator.data
            else "Hero",
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

        days = (
            slot_data.get("remaining_days")
            or slot_data.get("days_remaining")
            or slot_data.get("days")
        )
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
            "pills_remaining": slot_data.get("pills_remaining")
            or slot_data.get("remaining"),
            "pills_per_day": slot_data.get("pills_per_day")
            or slot_data.get("daily_count"),
        }
