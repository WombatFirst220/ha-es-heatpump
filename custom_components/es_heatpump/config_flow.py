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
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import (
    CONF_BASE_URL,
    CONF_FLOW_RATE,
    CONF_FLOW_RATE_DHW,
    CONF_MODE_SOURCE,
    CONF_DHW_MARGIN_K,
    CONF_FLOW_ENTITY,
    CONF_MODEL,
    CONF_POWER_ENTITY,
    CONF_SCAN_INTERVAL,
    DEFAULT_BASE_URL,
    DEFAULT_FLOW_RATE,
    DEFAULT_FLOW_RATE_DHW,
    DEFAULT_DHW_MARGIN_K,
    MODEL_UNKNOWN,
    NOMINAL_FLOW_RATES_M3H,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    KNOWN_BASE_URLS,
)


def _flow_rate_selector() -> NumberSelector:
    """Numeric input for a flow-rate value in m³/h."""
    return NumberSelector(
        NumberSelectorConfig(
            min=0.01, max=10.0, step=0.01, mode=NumberSelectorMode.BOX,
            unit_of_measurement="m³/h",
        )
    )


def _model_selector() -> SelectSelector:
    """Pick the unit so the datasheet nominal flow can be filled in."""
    return SelectSelector(
        SelectSelectorConfig(
            options=list(NOMINAL_FLOW_RATES_M3H) + [MODEL_UNKNOWN],
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


def _dhw_margin_selector() -> NumberSelector:
    """Vorlauf-ueber-Soll threshold that separates DHW from heating."""
    return NumberSelector(
        NumberSelectorConfig(
            min=2.0, max=25.0, step=0.5,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="K",
        )
    )


def _base_url_selector() -> SelectSelector:
    """Dropdown of known myheatpump.com regional portals, allowing custom values."""
    return SelectSelector(
        SelectSelectorConfig(
            options=KNOWN_BASE_URLS,
            mode=SelectSelectorMode.DROPDOWN,
            custom_value=True,
        )
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
                vol.Optional(
                    CONF_BASE_URL, default=DEFAULT_BASE_URL
                ): _base_url_selector(),
                vol.Optional(
                    CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                ): vol.All(int, vol.Range(min=10, max=3600)),
                vol.Optional(CONF_POWER_ENTITY): EntitySelector(
                    EntitySelectorConfig(domain="sensor", device_class="power")
                ),
                vol.Optional(CONF_MODE_SOURCE): EntitySelector(
                    EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    CONF_FLOW_RATE, default=DEFAULT_FLOW_RATE
                ): _flow_rate_selector(),
                vol.Optional(
                    CONF_FLOW_RATE_DHW, default=DEFAULT_FLOW_RATE_DHW
                ): _flow_rate_selector(),
                vol.Optional(
                    CONF_DHW_MARGIN_K, default=DEFAULT_DHW_MARGIN_K
                ): _dhw_margin_selector(),
                vol.Optional(CONF_MODEL, default=MODEL_UNKNOWN): _model_selector(),
                vol.Optional(CONF_FLOW_ENTITY): EntitySelector(
                    EntitySelectorConfig(domain="sensor")
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
            # Leere Entity-Felder AUSDRUECKLICH als "" ablegen, nicht verwerfen.
            # Wuerde der Schluessel fehlen, faende `opts.get(key, data.get(key))`
            # den bei der Einrichtung gesetzten Wert in entry.data wieder - eine
            # einmal gewaehlte Entity liesse sich dann nie mehr entfernen,
            # sondern nur ersetzen (Fehler bis v2.3.0).
            for key in (CONF_POWER_ENTITY, CONF_MODE_SOURCE, CONF_FLOW_ENTITY):
                if user_input.get(key) in (None, ""):
                    user_input[key] = ""

            # Modellwahl setzt den Volumenstrom auf den Nennwert des Datenblatts,
            # sobald sich das Modell geaendert hat. Danach bleibt der Wert von
            # Hand anpassbar.
            modell = user_input.get(CONF_MODEL)
            vorher = self._config_entry.options.get(
                CONF_MODEL, self._config_entry.data.get(CONF_MODEL)
            )
            if modell and modell != vorher and modell in NOMINAL_FLOW_RATES_M3H:
                user_input[CONF_FLOW_RATE] = NOMINAL_FLOW_RATES_M3H[modell][1]
                _LOGGER.info(
                    "ES Heatpump: Modell %s gewaehlt, Volumenstrom auf den "
                    "Nennwert %.2f m3/h gesetzt.",
                    modell, NOMINAL_FLOW_RATES_M3H[modell][1],
                )

            return self.async_create_entry(title="", data=user_input)

        opts = self._config_entry.options
        data = self._config_entry.data

        schema_dict: dict = {
            vol.Optional(
                CONF_BASE_URL,
                default=opts.get(CONF_BASE_URL, data.get(CONF_BASE_URL, DEFAULT_BASE_URL)),
            ): _base_url_selector(),
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
            ): _flow_rate_selector(),
            vol.Optional(
                CONF_FLOW_RATE_DHW,
                default=opts.get(
                    CONF_FLOW_RATE_DHW,
                    data.get(CONF_FLOW_RATE_DHW, DEFAULT_FLOW_RATE_DHW),
                ),
            ): _flow_rate_selector(),
            vol.Optional(
                CONF_DHW_MARGIN_K,
                default=opts.get(
                    CONF_DHW_MARGIN_K,
                    data.get(CONF_DHW_MARGIN_K, DEFAULT_DHW_MARGIN_K),
                ),
            ): _dhw_margin_selector(),
            vol.Optional(
                CONF_MODEL,
                default=opts.get(CONF_MODEL, data.get(CONF_MODEL, MODEL_UNKNOWN)),
            ): _model_selector(),
        }

        # Power-Entity is fully optional. If a value is already set, supply it
        # as default; otherwise leave the field empty.
        # WICHTIG: description={"suggested_value": ...} statt default=.
        # vol.Optional(key, default=X) setzt X ein, sobald der Schluessel fehlt -
        # ein geleertes Feld kaeme im Handler also nie als leer an, und die Entity
        # liesse sich nur ersetzen, nie entfernen (Fehler bis v2.4.0; v2.3.1 hatte
        # nur den Handler repariert, nicht das Schema). suggested_value fuellt das
        # Feld in der Oberflaeche vor, ohne beim Weglassen etwas einzusetzen.
        schema_dict[
            vol.Optional(
                CONF_POWER_ENTITY,
                description={"suggested_value": opts.get(
                    CONF_POWER_ENTITY, data.get(CONF_POWER_ENTITY)) or None},
            )
        ] = EntitySelector(EntitySelectorConfig(domain="sensor", device_class="power"))

        # Mode-source entity (any sensor, used to read the real operating mode)
        schema_dict[
            vol.Optional(
                CONF_MODE_SOURCE,
                description={"suggested_value": opts.get(
                    CONF_MODE_SOURCE, data.get(CONF_MODE_SOURCE)) or None},
            )
        ] = EntitySelector(EntitySelectorConfig(domain="sensor"))

        # Optionale Volumenstrom-Entity (beliebiger Sensor, m³/h, l/min, l/h, l/s)
        schema_dict[
            vol.Optional(
                CONF_FLOW_ENTITY,
                description={"suggested_value": opts.get(
                    CONF_FLOW_ENTITY, data.get(CONF_FLOW_ENTITY)) or None},
            )
        ] = EntitySelector(EntitySelectorConfig(domain="sensor"))

        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema_dict))
