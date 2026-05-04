"""The Techem DE Mieterportal integration."""

from __future__ import annotations

import calendar
import logging
from datetime import datetime, timedelta, timezone

import voluptuous as vol

from homeassistant.components.recorder.statistics import (
    async_import_statistics,
)
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMetaData,
    StatisticMeanType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform, UnitOfEnergy
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_PROPERTY_ID, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .techem_api import TechemApiClient, TechemApiError, TechemAuthError

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

SERVICE_IMPORT_HISTORY = "import_history"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Techem DE from a config entry."""
    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]
    property_id = entry.data.get(CONF_PROPERTY_ID, "")
    scan_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    client = TechemApiClient(email, password, property_id)

    async def async_update_data() -> dict:
        """Fetch data from the Techem API."""
        try:
            return await client.get_consumption_data()
        except TechemAuthError as err:
            raise UpdateFailed(f"Authentifizierung fehlgeschlagen: {err}") from err
        except TechemApiError as err:
            raise UpdateFailed(f"API-Fehler: {err}") from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=async_update_data,
        update_interval=timedelta(minutes=scan_interval),
    )

    # Initial data fetch
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register import_history service (once per integration)
    if not hass.services.has_service(DOMAIN, SERVICE_IMPORT_HISTORY):

        async def async_handle_import_history(call: ServiceCall) -> None:
            """Import historical consumption data into HA long-term statistics."""
            for eid, coord in hass.data[DOMAIN].items():
                await _import_history_for_coordinator(hass, eid, coord)

        hass.services.async_register(
            DOMAIN,
            SERVICE_IMPORT_HISTORY,
            async_handle_import_history,
            schema=vol.Schema({}),
        )

    return True


async def _import_history_for_coordinator(
    hass: HomeAssistant,
    entry_id: str,
    coordinator: DataUpdateCoordinator,
) -> None:
    """Build cumulative statistics from Techem history and import them."""
    if not coordinator.data or "services" not in coordinator.data:
        _LOGGER.warning("No data available for history import")
        return

    services = coordinator.data["services"]

    for service_key, service_data in services.items():
        kwh_history = service_data.get("kwh_history", [])
        if not kwh_history:
            continue

        # History is newest-first from the API, reverse for chronological order
        sorted_history = sorted(kwh_history, key=lambda x: x.get("period", ""))

        # Build cumulative sum statistics
        stats: list[StatisticData] = []
        cumulative = 0.0

        for item in sorted_history:
            period = item.get("period")  # Format: "YYYY-MM"
            value = item.get("value")
            if period is None or value is None:
                continue

            # Parse period to datetime (last day of month, midnight, UTC)
            try:
                year, month = period.split("-")
                last_day = calendar.monthrange(int(year), int(month))[1]
                start = datetime(int(year), int(month), last_day, 0, 0, 0, tzinfo=timezone.utc)
            except (ValueError, IndexError):
                _LOGGER.warning("Skipping invalid period: %s", period)
                continue

            cumulative = round(cumulative + value, 1)

            stats.append(
                StatisticData(
                    start=start,
                    state=cumulative,
                    sum=cumulative,
                )
            )

        if not stats:
            continue

        # Offset all sum values so the last entry has sum=0.
        # This ensures continuity with the live sensor statistics,
        # which start at sum=0 when the entity is first created
        # (TOTAL_INCREASING uses the first-seen value as zero-point).
        total_offset = stats[-1]["sum"]
        for stat in stats:
            stat["sum"] = round(stat["sum"] - total_offset, 1)

        # Find the actual entity_id of the Energy Dashboard sensor from the entity registry
        entity_registry = er.async_get(hass)
        target_unique_id = f"{entry_id}_{service_key}_energy_dashboard"
        statistic_id = None
        for entity in entity_registry.entities.values():
            if entity.unique_id == target_unique_id and entity.domain == "sensor":
                statistic_id = entity.entity_id
                break

        if not statistic_id:
            # Fallback: construct expected entity_id
            from .sensor import SERVICE_NAMES
            name = SERVICE_NAMES.get(service_key, service_key.replace("_", " ").title())
            statistic_id = f"sensor.techem_{name.lower()}_energieverbrauch_dashboard_"
            _LOGGER.warning(
                "Could not find entity for unique_id %s, using fallback: %s",
                target_unique_id,
                statistic_id,
            )

        metadata = StatisticMetaData(
            has_sum=True,
            mean_type=StatisticMeanType.NONE,
            name=f"Techem Energieverbrauch (Dashboard)",
            source="recorder",
            statistic_id=statistic_id,
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            unit_class="energy",
        )

        # Clear old statistics before importing new ones
        await hass.services.async_call(
            "recorder",
            "clear_statistics",
            {"statistic_ids": [statistic_id]},
            blocking=True,
        )
        _LOGGER.info("Cleared old statistics for %s", statistic_id)

        async_import_statistics(hass, metadata, stats)
        _LOGGER.info(
            "Imported %d historical statistics for %s (total: %.1f kWh)",
            len(stats),
            statistic_id,
            cumulative,
        )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
