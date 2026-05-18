"""Config flow for ES Heatpump integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import (
    CONF_BASE_URL,
    CONF_FLOW_RATE,
    CONF_POWER_ENTITY,
    CONF_SCAN_INTERVAL,
    DEFAULT_BASE_URL,
    DEFAULT_FLOW_RATE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .coordinator import ESHeatpumpCoordinator

_LOGGER = logging.getLogger(__name__)


class ESHeatpumpConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Initial setup flow."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_USERNAME].lower())
            self._abort_if_unique_id_configured()

            coordinator = ESHeatpumpCoordinator(
                hass=self.hass,
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
                base_url=user_input.get(CONF_BASE_URL, DEFAULT_BASE_URL),
                scan_interval=user_input.get(
                    CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                ),
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
                vol.Optional(
                    CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                ): vol.All(int, vol.Range(min=10, max=3600)),
                vol.Optional(CONF_POWER_ENTITY): EntitySelector(
                    EntitySelectorConfig(domain="sensor", device_class="power")
                ),
                vol.Optional(
                    CONF_FLOW_RATE, default=DEFAULT_FLOW_RATE
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.1, max=10.0, step=0.1, mode=NumberSelectorMode.BOX,
                        unit_of_measurement="m³/h",
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "flow_rate_help": (
                    "Volumenstrom des Heizkreislaufs in m³/h, "
                    "benötigt für die Berechnung der thermischen Leistung und des COP."
                ),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "ESHeatpumpOptionsFlow":
        return ESHeatpumpOptionsFlow(config_entry)


class ESHeatpumpOptionsFlow(config_entries.OptionsFlow):
    """Allow changing scan interval, base URL, power entity, flow rate."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            # Drop empty string from optional EntitySelector
            if user_input.get(CONF_POWER_ENTITY) in (None, ""):
                user_input.pop(CONF_POWER_ENTITY, None)
            return self.async_create_entry(title="", data=user_input)

        opts = self._config_entry.options
        data = self._config_entry.data

        schema_dict: dict = {
            vol.Optional(
                CONF_BASE_URL,
                default=opts.get(CONF_BASE_URL, data.get(CONF_BASE_URL, DEFAULT_BASE_URL)),
            ): str,
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=opts.get(
                    CONF_SCAN_INTERVAL,
                    data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ),
            ): vol.All(int, vol.Range(min=10, max=3600)),
            vol.Optional(
                CONF_FLOW_RATE,
                default=opts.get(
                    CONF_FLOW_RATE,
                    data.get(CONF_FLOW_RATE, DEFAULT_FLOW_RATE),
                ),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0.1, max=10.0, step=0.1, mode=NumberSelectorMode.BOX,
                    unit_of_measurement="m³/h",
                )
            ),
        }

        # Power-Entity is fully optional. If a value is already set, supply it
        # as default; otherwise leave the field empty.
        current_power = opts.get(CONF_POWER_ENTITY, data.get(CONF_POWER_ENTITY))
        if current_power:
            schema_dict[vol.Optional(CONF_POWER_ENTITY, default=current_power)] = (
                EntitySelector(EntitySelectorConfig(domain="sensor", device_class="power"))
            )
        else:
            schema_dict[vol.Optional(CONF_POWER_ENTITY)] = EntitySelector(
                EntitySelectorConfig(domain="sensor", device_class="power")
            )

        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema_dict))
