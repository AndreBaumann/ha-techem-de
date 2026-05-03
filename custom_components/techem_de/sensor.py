"""Sensor platform for Techem DE integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import CONF_PROPERTY_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Service key to friendly name mapping
SERVICE_NAMES = {
    "heating": "Heizung",
    "hot_water": "Warmwasser",
    "cold_water": "Kaltwasser",
    "cooling": "Kühlung",
}

SERVICE_ICONS = {
    "heating": "mdi:radiator",
    "hot_water": "mdi:water-thermometer",
    "cold_water": "mdi:water",
    "cooling": "mdi:snowflake",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Techem DE sensors from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = []

    if coordinator.data and "services" in coordinator.data:
        services = coordinator.data["services"]

        for service_key, service_data in services.items():
            # Main kWh consumption sensor
            if "kwh" in service_data:
                entities.append(
                    TechemConsumptionSensor(
                        coordinator=coordinator,
                        entry=entry,
                        service_key=service_key,
                    )
                )

            # Building average sensor
            if "kwh_average" in service_data:
                entities.append(
                    TechemAverageSensor(
                        coordinator=coordinator,
                        entry=entry,
                        service_key=service_key,
                    )
                )

            # HCU sensor (Heizkostenverteiler units)
            if "hcu" in service_data:
                entities.append(
                    TechemHCUSensor(
                        coordinator=coordinator,
                        entry=entry,
                        service_key=service_key,
                    )
                )

            # M3 sensor (cubic meters for water)
            if "m3" in service_data:
                entities.append(
                    TechemVolumeSensor(
                        coordinator=coordinator,
                        entry=entry,
                        service_key=service_key,
                    )
                )

            # Energy Dashboard sensor (cumulative kWh for HA Energy Dashboard)
            if "kwh" in service_data:
                entities.append(
                    TechemEnergyDashboardSensor(
                        coordinator=coordinator,
                        entry=entry,
                        service_key=service_key,
                    )
                )

    if not entities:
        _LOGGER.warning(
            "No consumption data available. Data: %s",
            coordinator.data,
        )

    async_add_entities(entities, True)


class TechemConsumptionSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Techem consumption in kWh."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        entry: ConfigEntry,
        service_key: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._service_key = service_key
        name = SERVICE_NAMES.get(service_key, service_key.replace("_", " ").title())
        self._attr_name = f"Techem {name}"
        self._attr_icon = SERVICE_ICONS.get(service_key, "mdi:meter-gas")
        self._attr_unique_id = f"{entry.entry_id}_{service_key}_kwh"

    @property
    def native_value(self) -> float | None:
        """Return the current consumption value."""
        if not self.coordinator.data or "services" not in self.coordinator.data:
            return None
        services = self.coordinator.data["services"]
        if self._service_key in services and "kwh" in services[self._service_key]:
            return services[self._service_key]["kwh"].get("value")
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes including history."""
        attrs: dict[str, Any] = {}
        if not self.coordinator.data:
            return attrs
        attrs["period"] = self.coordinator.data.get("period")
        services = self.coordinator.data.get("services", {})
        if self._service_key in services:
            svc = services[self._service_key]
            if "kwh" in svc:
                attrs["status"] = svc["kwh"].get("status")
                attrs["quality"] = svc["kwh"].get("quality")
            # Add history as period -> value mapping
            if "kwh_history" in svc:
                history = {}
                for item in svc["kwh_history"]:
                    period = item.get("period")
                    value = item.get("value")
                    if period and value is not None:
                        history[period] = value
                attrs["history"] = history
        return attrs


class TechemAverageSensor(CoordinatorEntity, SensorEntity):
    """Sensor for building average consumption."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        entry: ConfigEntry,
        service_key: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._service_key = service_key
        name = SERVICE_NAMES.get(service_key, service_key.replace("_", " ").title())
        self._attr_name = f"Techem {name} Gebäudedurchschnitt"
        self._attr_icon = "mdi:chart-bar"
        self._attr_unique_id = f"{entry.entry_id}_{service_key}_average"

    @property
    def native_value(self) -> float | None:
        """Return the building average value."""
        if not self.coordinator.data or "services" not in self.coordinator.data:
            return None
        services = self.coordinator.data["services"]
        if self._service_key in services and "kwh_average" in services[self._service_key]:
            return services[self._service_key]["kwh_average"].get("value")
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        attrs: dict[str, Any] = {}
        if self.coordinator.data:
            attrs["period"] = self.coordinator.data.get("period")
        return attrs


class TechemHCUSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Techem HCU (Heizkostenverteiler) units."""

    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "HCU"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        entry: ConfigEntry,
        service_key: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._service_key = service_key
        name = SERVICE_NAMES.get(service_key, service_key.replace("_", " ").title())
        self._attr_name = f"Techem {name} HCU"
        self._attr_icon = SERVICE_ICONS.get(service_key, "mdi:counter")
        self._attr_unique_id = f"{entry.entry_id}_{service_key}_hcu"

    @property
    def native_value(self) -> float | None:
        """Return the HCU value."""
        if not self.coordinator.data or "services" not in self.coordinator.data:
            return None
        services = self.coordinator.data["services"]
        if self._service_key in services and "hcu" in services[self._service_key]:
            return services[self._service_key]["hcu"].get("value")
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes including history."""
        attrs: dict[str, Any] = {}
        if not self.coordinator.data:
            return attrs
        attrs["period"] = self.coordinator.data.get("period")
        services = self.coordinator.data.get("services", {})
        if self._service_key in services:
            svc = services[self._service_key]
            if "hcu_history" in svc:
                history = {}
                for item in svc["hcu_history"]:
                    period = item.get("period")
                    value = item.get("value")
                    if period and value is not None:
                        history[period] = value
                attrs["history"] = history
        return attrs


class TechemVolumeSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Techem volume data (m³)."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        entry: ConfigEntry,
        service_key: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._service_key = service_key
        name = SERVICE_NAMES.get(service_key, service_key.replace("_", " ").title())
        self._attr_name = f"Techem {name} Volumen"
        self._attr_icon = "mdi:water"
        self._attr_unique_id = f"{entry.entry_id}_{service_key}_m3"

    @property
    def native_value(self) -> float | None:
        """Return the volume value."""
        if not self.coordinator.data or "services" not in self.coordinator.data:
            return None
        services = self.coordinator.data["services"]
        if self._service_key in services and "m3" in services[self._service_key]:
            return services[self._service_key]["m3"].get("value")
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        attrs: dict[str, Any] = {}
        if self.coordinator.data:
            attrs["period"] = self.coordinator.data.get("period")
        return attrs


class TechemEnergyDashboardSensor(CoordinatorEntity, RestoreEntity, SensorEntity):
    """Cumulative energy sensor for the HA Energy Dashboard.

    Sums all historical monthly consumption values into a single
    ever-increasing total so the Energy Dashboard can track usage correctly.
    """

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        entry: ConfigEntry,
        service_key: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._service_key = service_key
        name = SERVICE_NAMES.get(service_key, service_key.replace("_", " ").title())
        self._attr_name = f"Techem {name} Energieverbrauch (Dashboard)"
        self._attr_icon = SERVICE_ICONS.get(service_key, "mdi:meter-gas")
        self._attr_unique_id = f"{entry.entry_id}_{service_key}_energy_dashboard"
        self._cumulative: float | None = None
        self._last_period: str | None = None

    async def async_added_to_hass(self) -> None:
        """Restore previous cumulative value on HA restart."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (None, "unknown", "unavailable"):
            try:
                self._cumulative = float(last_state.state)
                self._last_period = (last_state.attributes or {}).get("last_period")
            except (ValueError, TypeError):
                self._cumulative = None

        # If no restored state, calculate from history
        if self._cumulative is None:
            self._cumulative = self._calculate_cumulative_from_history()

    def _calculate_cumulative_from_history(self) -> float | None:
        """Sum all historical kWh values to build the cumulative total."""
        if not self.coordinator.data or "services" not in self.coordinator.data:
            return None
        services = self.coordinator.data["services"]
        svc = services.get(self._service_key, {})
        history = svc.get("kwh_history", [])
        if not history:
            return None
        total = sum(
            item.get("value", 0) for item in history if item.get("value") is not None
        )
        if history:
            self._last_period = history[0].get("period")
        return round(total, 1)

    @property
    def native_value(self) -> float | None:
        """Return the cumulative consumption value."""
        if not self.coordinator.data or "services" not in self.coordinator.data:
            return self._cumulative
        services = self.coordinator.data["services"]
        svc = services.get(self._service_key, {})
        current_period = self.coordinator.data.get("period")

        # If period changed, add new month's consumption to cumulative total
        if current_period and current_period != self._last_period:
            kwh_data = svc.get("kwh", {})
            new_value = kwh_data.get("value")
            if new_value is not None and self._cumulative is not None:
                self._cumulative = round(self._cumulative + new_value, 1)
                self._last_period = current_period
            elif self._cumulative is None:
                self._cumulative = self._calculate_cumulative_from_history()

        return self._cumulative

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        attrs: dict[str, Any] = {}
        if self.coordinator.data:
            attrs["period"] = self.coordinator.data.get("period")
        attrs["last_period"] = self._last_period
        return attrs
