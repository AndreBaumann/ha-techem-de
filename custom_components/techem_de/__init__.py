"""The Techem DE Mieterportal integration."""

from __future__ import annotations

import calendar
import logging
from datetime import datetime, timedelta, timezone

import voluptuous as vol

from homeassistant.components.recorder import get_instance as get_recorder_instance
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
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_PROPERTY_ID, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .techem_api import TechemApiClient, TechemApiError, TechemAuthError

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

SERVICE_IMPORT_HISTORY = "import_history"
SERVICE_CLEAR_HISTORY = "clear_history"


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

    # Auto-import statistics after each coordinator update
    async def _auto_import_after_update() -> None:
        """Import statistics whenever the coordinator refreshes successfully."""
        if coordinator.data:
            await _import_history_for_coordinator(hass, entry.entry_id, coordinator, clear=False)

    coordinator.async_add_listener(lambda: hass.async_create_task(_auto_import_after_update()))

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

    # Register clear_history service (once per integration)
    if not hass.services.has_service(DOMAIN, SERVICE_CLEAR_HISTORY):

        async def async_handle_clear_history(call: ServiceCall) -> None:
            """Clear all statistics for dashboard entities."""
            for eid in hass.data[DOMAIN]:
                await _clear_history_for_entry(hass, eid)

        hass.services.async_register(
            DOMAIN,
            SERVICE_CLEAR_HISTORY,
            async_handle_clear_history,
            schema=vol.Schema({}),
        )

    return True


async def _import_history_for_coordinator(
    hass: HomeAssistant,
    entry_id: str,
    coordinator: DataUpdateCoordinator,
    clear: bool = True,
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

        # Use external statistics (source: "techem_de") to avoid recorder conflicts
        from .sensor import SERVICE_NAMES
        name = SERVICE_NAMES.get(service_key, service_key.replace("_", " ").title())
        statistic_id = f"{DOMAIN}:{service_key}_energy"

        metadata = StatisticMetaData(
            has_sum=True,
            mean_type=StatisticMeanType.NONE,
            name=f"Techem {name} Energieverbrauch",
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            unit_class="energy",
        )

        # Clear old statistics before importing new ones (only when explicitly requested)
        if clear:
            try:
                instance = get_recorder_instance(hass)
                instance.async_clear_statistics([statistic_id])
                _LOGGER.info("Cleared old statistics for %s", statistic_id)
            except Exception as err:
                _LOGGER.warning(
                    "Could not clear old statistics for %s: %s", statistic_id, err
                )

        async_import_statistics(hass, metadata, stats)
        _LOGGER.info(
            "Imported %d historical statistics for %s (total: %.1f kWh)",
            len(stats),
            statistic_id,
            cumulative,
        )


async def _clear_history_for_entry(
    hass: HomeAssistant,
    entry_id: str,
) -> None:
    """Clear all long-term statistics for dashboard entities of a config entry."""
    from .sensor import SERVICE_NAMES

    # Collect all external statistic_ids for this integration
    statistic_ids: list[str] = []
    for service_key in SERVICE_NAMES:
        statistic_ids.append(f"{DOMAIN}:{service_key}_energy")

    if not statistic_ids:
        _LOGGER.warning("No statistics found for entry %s", entry_id)
        return

    try:
        instance = get_recorder_instance(hass)
        instance.async_clear_statistics(statistic_ids)
        _LOGGER.info("Cleared statistics for: %s", statistic_ids)
    except Exception as err:
        _LOGGER.error("Failed to clear statistics: %s", err)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
