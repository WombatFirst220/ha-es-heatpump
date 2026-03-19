"""Config flow for ES Heatpump integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import (
    CONF_BASE_URL,
    CONF_SCAN_INTERVAL,
    DEFAULT_BASE_URL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .coordinator import ESHeatpumpCoordinator

_LOGGER = logging.getLogger(__name__)


class ESHeatpumpConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial setup flow shown to users in the HA UI."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """First (and only) step: ask for credentials and optional settings."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Deduplicate: prevent setting up the same account twice
            await self.async_set_unique_id(user_input[CONF_USERNAME].lower())
            self._abort_if_unique_id_configured()

            coordinator = ESHeatpumpCoordinator(
                hass=self.hass,
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
                base_url=user_input.get(CONF_BASE_URL, DEFAULT_BASE_URL),
                scan_interval=user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            )

            try:
                await coordinator.async_validate_credentials()
            except ConfigEntryAuthFailed:
                errors["base"] = "invalid_auth"
            except UpdateFailed:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during ES Heatpump setup")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"ES Heatpump ({user_input[CONF_USERNAME]})",
                    data=user_input,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
                    int, vol.Range(min=10, max=3600)
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ESHeatpumpOptionsFlow:
        """Return the options flow so users can change settings after setup."""
        return ESHeatpumpOptionsFlow(config_entry)


class ESHeatpumpOptionsFlow(config_entries.OptionsFlow):
    """Allow changing scan interval and base URL after initial setup."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_BASE_URL,
                    default=self._config_entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
                ): str,
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=self._config_entry.options.get(
                        CONF_SCAN_INTERVAL,
                        self._config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ),
                ): vol.All(int, vol.Range(min=10, max=3600)),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
