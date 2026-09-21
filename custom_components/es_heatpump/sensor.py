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
    BETRIEBSART_ALIASES,
    BETRIEBSART_OPTIONS,
    CALC_BETRIEBSART,
    CALC_COP,
    CALC_ELEC_POWER,
    CALC_SPREIZUNG,
    CALC_THERM_LEISTUNG,
    CONF_FLOW_RATE,
    CONF_FLOW_RATE_DHW,
    CONF_MODE_SOURCE,
    CONF_DHW_MARGIN_K,
    CONF_POWER_ENTITY,
    DEFAULT_FLOW_RATE,
    DEFAULT_FLOW_RATE_DHW,
    DEFAULT_DHW_MARGIN_K,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DEVICE_NAME,
    DOMAIN,
    PARAMETER_SENSORS,
    TEMP_SENTINEL,
    WATER_VOL_HEAT_CAPACITY_WH,
)
from .mode import derive_betriebsart as _derive_betriebsart


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — Betriebsart resolution + active flow-rate
# ─────────────────────────────────────────────────────────────────────────────
#
# v2.2.1 update: par15 was previously assumed to encode the operating mode
# but turned out to be a periodic heartbeat signal (toggles 0↔1 every ~10
# minutes, independent of actual operation).  The real mode is now read
# from a user-configured external entity (e.g. a multiscrape sensor that
# scrapes the portal's HTML "Unit Current Working Mode" field).  If no
# external source is configured, mode falls back to "Unbekannt" and the
# active flow rate defaults to the heating value (best-effort assumption,
# since heating dominates typical usage).

_NUMERIC_MODE_MAP = {0: "Aus", 1: "Brauchwasser", 2: "Heizen", 3: "Entfrosten"}
_PAREN_NUMBER_RE = __import__("re").compile(r"\(([-+]?\d+(?:\.\d+)?)\)")


def _mode_from_source(hass: HomeAssistant, mode_source: str | None) -> str:
    """Read the mode from an external helper entity (optional override)."""
    if not mode_source:
        return "Unbekannt"
    state = hass.states.get(mode_source)
    if state is None or state.state in ("unknown", "unavailable", ""):
        return "Unbekannt"
    raw = str(state.state).strip().lower()

    # Exact match in known aliases
    if raw in BETRIEBSART_ALIASES:
        return BETRIEBSART_ALIASES[raw]

    # Multiscrape-style "Unbekannt (0.0)" / "Unknown (2.0)" — pull the
    # numeric part out of the parentheses and map it.
    m = _PAREN_NUMBER_RE.search(raw)
    if m:
        try:
            as_int = int(float(m.group(1)))
            if as_int in _NUMERIC_MODE_MAP:
                return _NUMERIC_MODE_MAP[as_int]
        except (ValueError, TypeError):
            pass

    # Numeric fallback for sources that only return the par15-style int
    try:
        as_int = int(float(raw))
        if as_int in _NUMERIC_MODE_MAP:
            return _NUMERIC_MODE_MAP[as_int]
    except (ValueError, TypeError):
        pass
    return "Unbekannt"


def _resolve_betriebsart(
    hass: HomeAssistant,
    mode_source: str | None,
    data: dict[str, Any] | None = None,
    dhw_margin_k: float = DEFAULT_DHW_MARGIN_K,
) -> str:
    """Canonical operating mode.

    A configured ``mode_source_entity`` wins as long as it yields something
    usable — that keeps setups from v2.2.x working unchanged. Otherwise the
    mode is derived from the heat pump's own values (since v2.3.0), so no
    helper entity is required any more.
    """
    if mode_source:
        external = _mode_from_source(hass, mode_source)
        if external != "Unbekannt":
            return external
    if data:
        return _derive_betriebsart(data, dhw_margin_k)[0]
    return "Unbekannt"


def _active_flow_rate(
    mode: str, flow_heating: float, flow_dhw: float
) -> float:
    """Return the volumetric flow rate appropriate for the resolved mode."""
    if mode == "Heizen":
        return flow_heating
    if mode == "Brauchwasser":
        return flow_dhw
    if mode == "Unbekannt":
        # Should be rare since v2.3.0 (the mode is derived from own data).
        # Heating is the dominant mode, so it stays the best-effort guess.
        return flow_heating
    # "Aus" / "Entfrosten"
    return 0.0
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
    flow_rate_dhw = float(
        entry.options.get(
            CONF_FLOW_RATE_DHW,
            entry.data.get(CONF_FLOW_RATE_DHW, DEFAULT_FLOW_RATE_DHW),
        )
    )
    power_entity = entry.options.get(
        CONF_POWER_ENTITY,
        entry.data.get(CONF_POWER_ENTITY),
    ) or None
    mode_source = entry.options.get(
        CONF_MODE_SOURCE,
        entry.data.get(CONF_MODE_SOURCE),
    ) or None
    dhw_margin_k = float(
        entry.options.get(
            CONF_DHW_MARGIN_K,
            entry.data.get(CONF_DHW_MARGIN_K, DEFAULT_DHW_MARGIN_K),
        )
    )

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

    # ── Calculated / derived sensors ─────────────────────────────────────
    entities.append(SpreizungSensor(coordinator, device_info, username))
    entities.append(
        ThermLeistungSensor(
            coordinator, device_info, username,
            flow_rate, flow_rate_dhw, mode_source, hass, dhw_margin_k,
        )
    )
    entities.append(
        COPSensor(
            coordinator, device_info, username,
            flow_rate, flow_rate_dhw, power_entity, mode_source, hass, dhw_margin_k,
        )
    )
    entities.append(
        ElectricalPowerMirrorSensor(coordinator, device_info, username, power_entity, hass)
    )
    entities.append(
        BetriebsartCalcSensor(
            coordinator, device_info, username, mode_source, hass, dhw_margin_k
        )
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
        self._value_map: dict[float, str] | None = meta.get("value_map")
        self._attr_name = meta["name"]
        self._attr_unique_id = f"{DOMAIN}_{username}_{par_id}"
        self._attr_suggested_object_id = f"es_hp_{meta['slug']}"
        self._attr_native_unit_of_measurement = meta.get("unit")
        self._attr_device_class = meta.get("device_class")
        self._attr_state_class = meta.get("state_class")
        self._attr_icon = meta.get("icon")
        self._attr_entity_registry_enabled_default = meta.get("enabled_default", True)
        # `options` is required for device_class="enum" sensors
        if meta.get("options"):
            self._attr_options = list(meta["options"])
        self._attr_device_info = device_info

    @property
    def native_value(self) -> float | str | None:
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
        # Apply value mapping (e.g. par15: 2.0 → "Heizen") if configured
        if self._value_map is not None and value is not None:
            return self._value_map.get(value, "Unbekannt")
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {"parameter_id": self._par_id}
        # For enum sensors, also expose the raw numeric value for automations
        if self._value_map is not None and self.coordinator.data is not None:
            raw = self.coordinator.data.get(self._par_id)
            if raw is not None:
                attrs["raw_value"] = raw
        return attrs


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
    """Approximate heat output, mode-aware.

    P [W] = active_flow_rate [m³/h] × ΔT [K] × 1163 [Wh/(m³·K)]

    The active flow rate is selected based on the operation mode (par15):
      * Heizen   (par15=2) → ``flow_rate_heating``
      * Brauchwasser (par15=1) → ``flow_rate_dhw``
      * Off / Defrost / Unknown → 0

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
        flow_rate_heating: float,
        flow_rate_dhw: float,
        mode_source: str | None,
        hass: HomeAssistant,
        dhw_margin_k: float = DEFAULT_DHW_MARGIN_K,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{username}_{CALC_THERM_LEISTUNG}"
        self._attr_suggested_object_id = "es_hp_thermische_leistung"
        self._attr_device_info = device_info
        self._flow_heating = flow_rate_heating
        self._flow_dhw = flow_rate_dhw
        self._mode_source = mode_source
        self._hass = hass
        self._dhw_margin_k = dhw_margin_k

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data or {}
        vor, rue, freq = data.get("par4"), data.get("par5"), data.get("par20")
        if vor is None or rue is None:
            return None
        if not freq or freq <= 0:
            return 0.0
        mode = _resolve_betriebsart(
            self._hass, self._mode_source, data, self._dhw_margin_k
        )
        active_flow = _active_flow_rate(mode, self._flow_heating, self._flow_dhw)
        if active_flow <= 0:
            return 0.0
        delta_t = vor - rue
        if delta_t <= 0:
            return 0.0
        return round(active_flow * delta_t * WATER_VOL_HEAT_CAPACITY_WH, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "flow_rate_heating_m3h": self._flow_heating,
            "flow_rate_dhw_m3h": self._flow_dhw,
            "mode_source": self._mode_source,
            "resolved_mode": _resolve_betriebsart(
                self._hass, self._mode_source, self.coordinator.data, self._dhw_margin_k
            ),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Calculated: COP = Thermal / Electrical
# ─────────────────────────────────────────────────────────────────────────────

class COPSensor(CoordinatorEntity[ESHeatpumpCoordinator], SensorEntity):
    """Coefficient of Performance, mode-aware.

    Uses ``flow_rate_heating`` in Heizen mode (par15=2) and
    ``flow_rate_dhw`` in Brauchwasser mode (par15=1).  Returns 0 in off /
    defrost / unknown modes because there is no useful heat delivery.

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
        flow_rate_heating: float,
        flow_rate_dhw: float,
        power_entity: str | None,
        mode_source: str | None,
        hass: HomeAssistant,
        dhw_margin_k: float = DEFAULT_DHW_MARGIN_K,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{username}_{CALC_COP}"
        self._attr_suggested_object_id = "es_hp_aktueller_cop"
        self._attr_device_info = device_info
        self._flow_heating = flow_rate_heating
        self._flow_dhw = flow_rate_dhw
        self._power_entity = power_entity
        self._mode_source = mode_source
        self._hass = hass
        self._dhw_margin_k = dhw_margin_k
        self._warned_implausible = False

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

        mode = _resolve_betriebsart(
            self._hass, self._mode_source, data, self._dhw_margin_k
        )
        active_flow = _active_flow_rate(mode, self._flow_heating, self._flow_dhw)
        if active_flow <= 0:
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

        therm_w = active_flow * (vor - rue) * WATER_VOL_HEAT_CAPACITY_WH
        if therm_w <= 0:
            return 0.0
        cop = therm_w / elec_w

        # Plausibilitaetspruefung: Ein COP unter 1 bedeutet, die Maschine gaebe
        # weniger Waerme ab als sie Strom aufnimmt - physikalisch unmoeglich.
        # Da die thermische Leistung aus dem EINGESTELLTEN Volumenstrom
        # gerechnet wird, ist praktisch immer dieser zu niedrig. Einmal pro
        # Neustart warnen, nicht bei jedem Messwert.
        if cop < 1.0 and not self._warned_implausible:
            self._warned_implausible = True
            _LOGGER.warning(
                "ES Heatpump: COP %.2f im Betrieb (%s) ist physikalisch unmoeglich. "
                "Die thermische Leistung wird aus dem eingestellten Volumenstrom "
                "berechnet (aktuell %.2f m3/h) - dieser Wert ist zu niedrig. "
                "Richtwert aus dem Datenblatt der AWC-R32-M-Serie, Zeile "
                "'Zulaessiger Wasserdurchfluss Min/Nominal': AWC6 1.01, AWC9 1.55, "
                "AWC12 2.02, AWC15 2.59, AWC19 3.28 m3/h (Nominalwert). "
                "In den Integrationsoptionen unter 'Volumenstrom Heizkreislauf' "
                "korrigieren.",
                cop, mode, active_flow,
            )
        elif cop >= 1.0:
            self._warned_implausible = False

        return round(cop, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "power_entity": self._power_entity,
            "flow_rate_heating_m3h": self._flow_heating,
            "flow_rate_dhw_m3h": self._flow_dhw,
            "mode_source": self._mode_source,
            "resolved_mode": _resolve_betriebsart(
                self._hass, self._mode_source, self.coordinator.data, self._dhw_margin_k
            ),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Calculated: Betriebsart (read from external mode_source entity)
# ─────────────────────────────────────────────────────────────────────────────

class BetriebsartCalcSensor(
    CoordinatorEntity[ESHeatpumpCoordinator], SensorEntity
):
    """Operating-mode sensor, derived from the heat pump's own values.

    The portal's raw API has no clean operating-mode field — par15 turned out
    to be a heartbeat signal. Up to v2.2.x the mode therefore had to come from
    an external helper entity (typically a multiscrape sensor reading the
    portal's HTML "Unit Current Working Mode"), and stayed "Unbekannt" without
    one.

    Since v2.3.0 the mode is derived from compressor frequency, spread and the
    distance between flow temperature and heating setpoint — no helper entity
    needed. A configured ``mode_source_entity`` still takes precedence when it
    yields a usable value, so existing setups are unaffected.

    The attribute ``begruendung`` states which rule fired, so the decision can
    be checked in the UI without reading the source.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Betriebsart"
    _attr_device_class = "enum"
    _attr_options = BETRIEBSART_OPTIONS
    _attr_icon = "mdi:heat-pump"

    def __init__(
        self,
        coordinator,
        device_info: DeviceInfo,
        username: str,
        mode_source: str | None,
        hass: HomeAssistant,
        dhw_margin_k: float = DEFAULT_DHW_MARGIN_K,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{username}_{CALC_BETRIEBSART}"
        self._attr_suggested_object_id = "es_hp_betriebsart"
        self._attr_device_info = device_info
        self._mode_source = mode_source
        self._hass = hass
        self._dhw_margin_k = dhw_margin_k

    @property
    def native_value(self) -> str:
        return _resolve_betriebsart(
            self._hass, self._mode_source, self.coordinator.data, self._dhw_margin_k
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        abgeleitet, begruendung = _derive_betriebsart(data, self._dhw_margin_k)

        externe = _mode_from_source(self._hass, self._mode_source) if self._mode_source else "Unbekannt"
        quelle = "externe Entity" if externe != "Unbekannt" else "eigene Werte"

        attrs: dict[str, Any] = {
            "quelle": quelle,
            "begruendung": begruendung,
            "abgeleitet_aus_eigenen_werten": abgeleitet,
            "dhw_margin_k": self._dhw_margin_k,
            "vorlauf_c": data.get("par4"),
            "ruecklauf_c": data.get("par5"),
            "heizen_soll_c": data.get("par6"),
            "kompressor_hz": data.get("par20"),
            "mode_source": self._mode_source,
        }
        if self._mode_source:
            state = self._hass.states.get(self._mode_source)
            attrs["source_raw"] = state.state if state else None
        # Diagnostic: expose the non-parXX response keys from the portal API
        # so we can later identify a native mode field without code changes.
        raw_meta = (self.coordinator.data or {}).get("_raw_meta")
        if raw_meta:
            attrs["api_response_meta"] = raw_meta
        return attrs


# ─────────────────────────────────────────────────────────────────────────────
# Mirror: Elektrische Leistung (from the configured Power-Entity)
# ─────────────────────────────────────────────────────────────────────────────

class ElectricalPowerMirrorSensor(
    CoordinatorEntity[ESHeatpumpCoordinator], SensorEntity
):
    """Mirror of the user-configured electrical-power sensor.

    Exposed under the ES Heatpump device so the dashboard / automations have
    a consistent ``sensor.es_hp_leistung_elektrisch`` to bind to, independent
    of the specific Shelly/Smart-meter entity the user picked in the options.

    The sensor returns the absolute value of the source entity — many
    energy meters report power as negative when the meter is in
    consumption direction.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Elektrische Leistung"
    _attr_native_unit_of_measurement = "W"
    _attr_device_class = "power"
    _attr_state_class = "measurement"
    _attr_icon = "mdi:lightning-bolt"
    _attr_suggested_display_precision = 0

    def __init__(
        self,
        coordinator,
        device_info: DeviceInfo,
        username: str,
        power_entity: str | None,
        hass: HomeAssistant,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{username}_{CALC_ELEC_POWER}"
        self._attr_suggested_object_id = "es_hp_leistung_elektrisch"
        self._attr_device_info = device_info
        self._power_entity = power_entity
        self._hass = hass

    @property
    def available(self) -> bool:
        return self._power_entity is not None

    @property
    def native_value(self) -> float | None:
        if not self._power_entity:
            return None
        state = self._hass.states.get(self._power_entity)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return round(abs(float(state.state)), 1)
        except (ValueError, TypeError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"power_entity": self._power_entity}
