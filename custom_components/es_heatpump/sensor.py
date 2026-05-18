"""Sensor platform for ES Heatpump integration.

Creates:
  • One ESHeatpumpSensor per parameter listed in PARAMETER_SENSORS (const.py).
    Unknown / always-zero parameters are intentionally NOT exposed.
  • Three calculated sensors that derive useful values from the raw data:
      - Spreizung (Vorlauf − Rücklauf)
      - Thermische Leistung (kJ delivered to the heating circuit)
      - Aktueller COP   (thermal / electrical, requires Power-Entity in config)

Entity-IDs are forced to the form ``sensor.es_hp_<slug>`` via
``_attr_suggested_object_id`` so they are stable across name changes.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CALC_COP,
    CALC_SPREIZUNG,
    CALC_THERM_LEISTUNG,
    CONF_FLOW_RATE,
    CONF_POWER_ENTITY,
    DEFAULT_FLOW_RATE,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DEVICE_NAME,
    DOMAIN,
    PARAMETER_SENSORS,
    TEMP_SENTINEL,
    WATER_VOL_HEAT_CAPACITY_WH,
)
from .coordinator import ESHeatpumpCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors for one ES Heatpump config entry."""
    coordinator: ESHeatpumpCoordinator = hass.data[DOMAIN][entry.entry_id]
    username = entry.data[CONF_USERNAME]

    device_info = DeviceInfo(
        identifiers={(DOMAIN, username)},
        name=DEVICE_NAME,
        manufacturer=DEVICE_MANUFACTURER,
        model=DEVICE_MODEL,
        configuration_url=coordinator._base_url,
    )

    # Read calculation settings from options first, fallback to initial data
    flow_rate = float(
        entry.options.get(
            CONF_FLOW_RATE,
            entry.data.get(CONF_FLOW_RATE, DEFAULT_FLOW_RATE),
        )
    )
    power_entity = entry.options.get(
        CONF_POWER_ENTITY,
        entry.data.get(CONF_POWER_ENTITY),
    ) or None

    entities: list[SensorEntity] = []

    # ── Raw parameter sensors ────────────────────────────────────────────
    for par_id, meta in PARAMETER_SENSORS.items():
        entities.append(
            ESHeatpumpSensor(
                coordinator=coordinator,
                device_info=device_info,
                par_id=par_id,
                meta=meta,
                username=username,
            )
        )

    # ── Calculated sensors ───────────────────────────────────────────────
    entities.append(SpreizungSensor(coordinator, device_info, username))
    entities.append(
        ThermLeistungSensor(coordinator, device_info, username, flow_rate)
    )
    entities.append(
        COPSensor(coordinator, device_info, username, flow_rate, power_entity, hass)
    )

    _LOGGER.info(
        "ES Heatpump: creating %d entities (%d raw, 3 calculated)",
        len(entities), len(PARAMETER_SENSORS),
    )
    async_add_entities(entities)


# ─────────────────────────────────────────────────────────────────────────────
# Raw parameter sensor
# ─────────────────────────────────────────────────────────────────────────────

class ESHeatpumpSensor(CoordinatorEntity[ESHeatpumpCoordinator], SensorEntity):
    """Sensor wrapping a single ``parXX`` value from the portal."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: ESHeatpumpCoordinator,
        device_info: DeviceInfo,
        par_id: str,
        meta: dict[str, Any],
        username: str,
    ) -> None:
        super().__init__(coordinator)
        self._par_id = par_id
        self._attr_name = meta["name"]
        self._attr_unique_id = f"{DOMAIN}_{username}_{par_id}"
        self._attr_suggested_object_id = f"es_hp_{meta['slug']}"
        self._attr_native_unit_of_measurement = meta.get("unit")
        self._attr_device_class = meta.get("device_class")
        self._attr_state_class = meta.get("state_class")
        self._attr_icon = meta.get("icon")
        self._attr_entity_registry_enabled_default = meta.get("enabled_default", True)
        self._attr_device_info = device_info

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        value = self.coordinator.data.get(self._par_id)
        # Filter the -99 sentinel emitted by the portal for disconnected
        # temperature probes (e.g. Mischventil 2 when unused).
        if (
            value == TEMP_SENTINEL
            and self._attr_device_class == "temperature"
        ):
            return None
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"parameter_id": self._par_id}


# ─────────────────────────────────────────────────────────────────────────────
# Calculated: Spreizung (Vorlauf − Rücklauf)
# ─────────────────────────────────────────────────────────────────────────────

class SpreizungSensor(CoordinatorEntity[ESHeatpumpCoordinator], SensorEntity):
    """Delta-T between Vorlauf (par4) and Rücklauf (par5)."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Spreizung"
    _attr_native_unit_of_measurement = "K"
    _attr_device_class = "temperature"
    _attr_state_class = "measurement"
    _attr_icon = "mdi:delta"

    def __init__(self, coordinator, device_info: DeviceInfo, username: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{username}_{CALC_SPREIZUNG}"
        self._attr_suggested_object_id = "es_hp_spreizung"
        self._attr_device_info = device_info

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data or {}
        vor, rue = data.get("par4"), data.get("par5")
        if vor is None or rue is None:
            return None
        return round(vor - rue, 2)


# ─────────────────────────────────────────────────────────────────────────────
# Calculated: Thermische Leistung (Wärmeabgabe)
# ─────────────────────────────────────────────────────────────────────────────

class ThermLeistungSensor(CoordinatorEntity[ESHeatpumpCoordinator], SensorEntity):
    """Approximate heat output to the heating circuit.

    P [W] = flow_rate [m³/h] × ΔT [K] × 1163 [Wh/(m³·K)]

    Returns 0 when the compressor is idle (par20 = 0) regardless of ΔT,
    because a residual temperature differential in standby is not delivered
    power.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Thermische Leistung"
    _attr_native_unit_of_measurement = "W"
    _attr_device_class = "power"
    _attr_state_class = "measurement"
    _attr_icon = "mdi:fire"

    def __init__(
        self,
        coordinator,
        device_info: DeviceInfo,
        username: str,
        flow_rate: float,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{username}_{CALC_THERM_LEISTUNG}"
        self._attr_suggested_object_id = "es_hp_thermische_leistung"
        self._attr_device_info = device_info
        self._flow_rate = flow_rate

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data or {}
        vor, rue, freq = data.get("par4"), data.get("par5"), data.get("par20")
        if vor is None or rue is None:
            return None
        if not freq or freq <= 0:
            return 0.0
        delta_t = vor - rue
        if delta_t <= 0:
            return 0.0
        return round(self._flow_rate * delta_t * WATER_VOL_HEAT_CAPACITY_WH, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"flow_rate_m3h": self._flow_rate}


# ─────────────────────────────────────────────────────────────────────────────
# Calculated: COP = Thermal / Electrical
# ─────────────────────────────────────────────────────────────────────────────

class COPSensor(CoordinatorEntity[ESHeatpumpCoordinator], SensorEntity):
    """Coefficient of Performance.

    Requires a separate electrical-power sensor (e.g. Shelly) configured
    via the Options Flow. Without it the sensor stays at ``None``.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Aktueller COP"
    _attr_native_unit_of_measurement = None
    _attr_state_class = "measurement"
    _attr_icon = "mdi:chart-bell-curve"
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        coordinator,
        device_info: DeviceInfo,
        username: str,
        flow_rate: float,
        power_entity: str | None,
        hass: HomeAssistant,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{username}_{CALC_COP}"
        self._attr_suggested_object_id = "es_hp_aktueller_cop"
        self._attr_device_info = device_info
        self._flow_rate = flow_rate
        self._power_entity = power_entity
        self._hass = hass

    @property
    def native_value(self) -> float | None:
        if not self._power_entity:
            return None
        data = self.coordinator.data or {}
        vor, rue, freq = data.get("par4"), data.get("par5"), data.get("par20")
        if vor is None or rue is None:
            return None
        if not freq or freq <= 0:
            return 0.0

        state = self._hass.states.get(self._power_entity)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            elec_w = abs(float(state.state))
        except (ValueError, TypeError):
            return None
        if elec_w < 50:    # below this we treat the heatpump as effectively idle
            return 0.0

        therm_w = self._flow_rate * (vor - rue) * WATER_VOL_HEAT_CAPACITY_WH
        if therm_w <= 0:
            return 0.0
        return round(therm_w / elec_w, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "power_entity": self._power_entity,
            "flow_rate_m3h": self._flow_rate,
        }
