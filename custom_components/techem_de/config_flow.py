"""Config flow for Techem DE integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_PROPERTY_ID,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .techem_api import TechemApiClient, TechemAuthError

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_PROPERTY_ID, default=""): str,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            int, vol.Range(min=60, max=1440)
        ),
    }
)


class TechemDEConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Techem DE."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]
            property_id = user_input.get(CONF_PROPERTY_ID, "")

            # Test the connection
            client = TechemApiClient(email, password, property_id)

            try:
                await client.authenticate()
                # If property_id was empty, it may now be auto-detected from the token
                if not property_id and client.property_id:
                    property_id = client.property_id
            except TechemAuthError as err:
                _LOGGER.error("Authentication failed: %s", err)
                errors["base"] = "invalid_auth"
            except Exception as err:
                _LOGGER.exception("Unexpected error during authentication")
                errors["base"] = "cannot_connect"

            if not errors and not property_id:
                errors["base"] = "no_property_id"

            if not errors:
                # Ensure unique entry per email
                await self.async_set_unique_id(email.lower())
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Techem ({email})",
                    data={
                        CONF_EMAIL: email,
                        CONF_PASSWORD: password,
                        CONF_PROPERTY_ID: property_id,
                        CONF_SCAN_INTERVAL: user_input.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
