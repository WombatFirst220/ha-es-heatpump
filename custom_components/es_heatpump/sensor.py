"""Sensor platform for ES Heatpump integration.

Creates:
  • One ESHeatpumpSensor per parameter listed in PARAMETER_SENSORS (const.py).
    Unknown / always-zero parameters are intentionally NOT exposed.
  • Three calculated sensors that derive useful values from the raw data:
      - Spreizung (Vorlauf − Rücklauf)
      - Thermische Leistung (kJ delivered to the heating circuit)
      - Aktueller COP   (thermal / electrical, requires Power-Entity in config)
  • Zaehler fuer die Auswertungsseite: elektrische und thermische Energie
    (kWh, gesamt/Heizen/Warmwasser), Verdichterstarts und -laufzeit. Logik in
    ``energy.py``; Zaehlerstaende werden ueber RestoreSensor fortgesetzt.

Entity-IDs: Jede Entity setzt ``self.entity_id = "sensor.es_hp_<slug>"``
ausdruecklich. Bis v3.2.0 stand hier ``_attr_suggested_object_id`` - dieses
Attribut kennt Home Assistant nicht, es wurde stillschweigend ignoriert. Neue
Installationen bekamen deshalb zuerst eine ID aus Geraetename + Name
(``sensor.es_warmepumpe_vorlauftemperatur``), die erst die Migration in
``__init__.py`` auf ``sensor.es_hp_<slug>`` umschrieb. Seit GitHub-Issue #6 steht die
richtige ID von Anfang an da. Ein vorhandener Registereintrag hat immer Vorrang,
bestehende Installationen behalten ihre IDs also unveraendert.

Namen und Zustaende (GitHub-Issue #6): ``_attr_has_entity_name = True`` plus
``_attr_translation_key``; die Texte stehen in ``strings.json`` bzw.
``translations/<sprache>.json`` unter ``entity.sensor.<key>``.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .device import baue_device_info

from .const import (
    BETRIEBSART_ALIASES,
    BETRIEBSART_STATE_KEYS,
    BETRIEBSART_STATE_OPTIONS,
    CALC_BETRIEBSART,
    CALC_COP,
    CALC_ELEC_POWER,
    CALC_SPREIZUNG,
    CALC_THERM_LEISTUNG,
    CONF_FLOW_RATE,
    CONF_FLOW_RATE_DHW,
    CONF_MODE_SOURCE,
    CONF_DHW_MARGIN_K,
    CONF_FLOW_ENTITY,
    CONF_ENERGY_ENTITY,
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
)
from .mode import (
    betriebsart_aus_par1 as _betriebsart_aus_par1,
    derive_betriebsart as _derive_betriebsart,
    ist_abtauen as _ist_abtauen,
)
from .flow import active_flow_rate as _active_flow_rate, flow_from_entity
from .energy import (
    ART_ELEKTRISCH,
    ART_THERMISCH,
    ENERGIE_ZAEHLER,
    GESAMT,
    MAX_LUECKE_ELEKTRISCH_S,
    MAX_LUECKE_THERMISCH_S,
    MAX_LUECKE_VERDICHTER_S,
    METHODE_LINKS,
    METHODE_TRAPEZ,
    EnergieZaehler,
    VerdichterZaehler,
    ZaehlerstandFolger,
    energie_in_kwh,
    kategorie_von,
    leistung_in_w,
    thermische_leistung_w,
)


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


def _live_flow(hass: HomeAssistant, flow_entity: str | None) -> tuple[float | None, str]:
    """Read the optional live flow sensor, converted to m³/h."""
    if not flow_entity:
        return None, "keine Volumenstrom-Entity konfiguriert"
    return flow_from_entity(hass.states.get(flow_entity))


# Temperaturdifferenz-Geraeteklasse (v4.0.1). TEMPERATURE_DELTA gibt es erst in
# neueren HA-Versionen; ohne sie lieber gar keine Klasse als "temperature" -
# letztere rechnet eine Differenz in K als absolute Temperatur um (-268 °C).
_DEVICE_CLASS_DELTA = getattr(SensorDeviceClass, "TEMPERATURE_DELTA", None)


def _geraeteklasse(wert: str | None) -> Any:
    """Bildet den Katalogwert aus const.py auf eine HA-Geraeteklasse ab."""
    if wert == "temperature_delta":
        return _DEVICE_CLASS_DELTA
    return wert


# Zwischenspeicher fuer _resolve_betriebsart (v4.0.1). Bis zu acht Entities
# fragten je Abruf dieselbe Betriebsart ab, jede rechnete sie vollstaendig neu.
# Schluessel: Datenstand des Koordinators (Objekt-Identitaet, gegen
# Wiederverwendung der id() durch die mitgehaltene Referenz abgesichert),
# Optionen und Zustand der externen Betriebsart-Entity. Das Ergebnis ist damit
# exakt dasselbe wie ohne Zwischenspeicher.
_BETRIEBSART_CACHE: dict[tuple, tuple[Any, tuple[str, str]]] = {}
_BETRIEBSART_CACHE_MAX = 32


def _resolve_betriebsart(
    hass: HomeAssistant,
    mode_source: str | None,
    data: dict[str, Any] | None = None,
    dhw_margin_k: float = DEFAULT_DHW_MARGIN_K,
) -> tuple[str, str]:
    """Wie ``_resolve_betriebsart_neu``, aber je Datenstand nur einmal gerechnet."""
    if not data:
        return _resolve_betriebsart_neu(hass, mode_source, data, dhw_margin_k)
    quelle_zustand = None
    if mode_source:
        state = hass.states.get(mode_source)
        quelle_zustand = state.state if state is not None else None
    schluessel = (id(data), mode_source, dhw_margin_k, quelle_zustand)
    treffer = _BETRIEBSART_CACHE.get(schluessel)
    if treffer is not None and treffer[0] is data:
        return treffer[1]
    ergebnis = _resolve_betriebsart_neu(hass, mode_source, data, dhw_margin_k)
    if len(_BETRIEBSART_CACHE) >= _BETRIEBSART_CACHE_MAX:
        _BETRIEBSART_CACHE.clear()
    _BETRIEBSART_CACHE[schluessel] = (data, ergebnis)
    return ergebnis


def _resolve_betriebsart_neu(
    hass: HomeAssistant,
    mode_source: str | None,
    data: dict[str, Any] | None = None,
    dhw_margin_k: float = DEFAULT_DHW_MARGIN_K,
) -> tuple[str, str]:
    """Canonical operating mode, with the reason as second element.

    Order of precedence:

    1. **``par1``** — the unit's own "Unit Current Working Mode" (since
       v2.4.0). Authoritative, because it is what the machine reports.
    2. **``mode_source_entity``** — the external helper some setups configured
       before v2.4.0. It reads the same information from the portal's HTML, one
       step removed, so it only applies when ``par1`` is unavailable.
    3. **derivation** from frequency, spread and flow-vs-setpoint (v2.3.0) —
       the fallback for units that report no ``par1``.

    On top of that: defrosting is not a mode in the portal's vocabulary. While
    the cycle runs in reverse the unit keeps reporting "Heating", so that case
    is corrected here.
    """
    data = data or {}

    modus, grund = _betriebsart_aus_par1(data)
    if modus is None and mode_source:
        extern = _mode_from_source(hass, mode_source)
        if extern != "Unbekannt":
            modus, grund = extern, f"externe Entity {mode_source} meldet {extern}"
    if modus is None and data:
        modus, grund = _derive_betriebsart(data, dhw_margin_k)
    if modus is None:
        return "Unbekannt", grund

    if modus in ("Heizen", "Brauchwasser + Heizen") and _ist_abtauen(data):
        return "Entfrosten", (
            f"{grund}, aber Vorlauf unter Rücklauf — Kreisprozess umgekehrt"
        )
    return modus, grund


from .coordinator import ESHeatpumpCoordinator

_LOGGER = logging.getLogger(__name__)

# Abrufe laufen ueber die Koordinatoren; keine Begrenzung noetig.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors for one ES Heatpump config entry."""
    # Seit v3.0.0 liegt unter der Eintrags-Kennung ein Buendel statt eines
    # einzelnen Koordinators - Messwerte, Konfiguration, Sicherungsablage.
    _daten = hass.data[DOMAIN][entry.entry_id]
    coordinator: ESHeatpumpCoordinator = _daten["api"]
    username = entry.data[CONF_USERNAME]

    # Modell, Seriennummer und Firmware kommen seit v3.0.0 aus dem Portal.
    _settings = _daten.get("settings")
    device_info = baue_device_info(
        username,
        coordinator._base_url,
        coordinator.stammdaten,
        _settings.data if _settings is not None else None,
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
    energy_entity = entry.options.get(
        CONF_ENERGY_ENTITY,
        entry.data.get(CONF_ENERGY_ENTITY),
    ) or None
    mode_source = entry.options.get(
        CONF_MODE_SOURCE,
        entry.data.get(CONF_MODE_SOURCE),
    ) or None
    flow_entity = entry.options.get(
        CONF_FLOW_ENTITY,
        entry.data.get(CONF_FLOW_ENTITY),
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
            flow_rate, flow_rate_dhw, mode_source, hass, dhw_margin_k, flow_entity,
        )
    )
    entities.append(
        COPSensor(
            coordinator, device_info, username,
            flow_rate, flow_rate_dhw, power_entity, mode_source, hass, dhw_margin_k, flow_entity,
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

    # ── Stammdaten und Sicherungsstand (v3.0.0) ──────────────────────────
    entities.append(StammdatenSensor(coordinator, device_info, username))
    if _settings is not None:
        entities.append(SicherungenSensor(_settings, device_info, username))

    # ── Energiezaehler fuer die Auswertungsseite ─────────────────────────
    bilanz = EnergieBilanz(
        hass, coordinator, power_entity, mode_source, dhw_margin_k,
        flow_rate, flow_rate_dhw, flow_entity, energy_entity,
    )
    zaehler_entities = [
        EnergieZaehlerSensor(bilanz, device_info, username, slug, art, teil)
        for slug, art, teil in ENERGIE_ZAEHLER
    ] + [
        VerdichterStartsSensor(bilanz, device_info, username),
        VerdichterLaufzeitSensor(bilanz, device_info, username),
    ]
    entities.extend(zaehler_entities)

    _LOGGER.info(
        "ES Heatpump: creating %d entities (%d raw, calculated + diagnostics)",
        len(entities), len(PARAMETER_SENSORS),
    )
    async_add_entities(entities)
    entry.async_on_unload(bilanz.async_starte())


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
        # value_map wird derzeit von keinem Parameter genutzt. Falls doch
        # wieder: Die Werte muessen Zustands-Schluessel ([a-z0-9_]) sein, die
        # unter entity.sensor.<slug>.state uebersetzt sind.
        self._value_map: dict[float, str] | None = meta.get("value_map")
        self._attr_translation_key = meta["slug"]
        self._attr_unique_id = f"{DOMAIN}_{username}_{par_id}"
        self.entity_id = f"sensor.es_hp_{meta['slug']}"
        self._attr_native_unit_of_measurement = meta.get("unit")
        self._attr_device_class = _geraeteklasse(meta.get("device_class"))
        # Fuer den -99-Filter zaehlt der Katalogwert, nicht die HA-Klasse
        # (eine Temperaturdifferenz hat je nach HA-Version gar keine).
        self._ist_temperatur = meta.get("device_class") in (
            "temperature", "temperature_delta"
        )
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
            and self._ist_temperatur
        ):
            return None
        # Apply value mapping (state keys, translated via translation_key)
        if self._value_map is not None and value is not None:
            return self._value_map.get(value, "unknown")
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
    _attr_translation_key = "spreizung"
    _attr_native_unit_of_measurement = "K"
    # Differenz, keine absolute Temperatur - siehe _geraeteklasse(). Die
    # Einheit bleibt K, die Langzeitstatistik damit unveraendert.
    _attr_device_class = _DEVICE_CLASS_DELTA
    _attr_state_class = "measurement"
    _attr_icon = "mdi:delta"

    def __init__(self, coordinator, device_info: DeviceInfo, username: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{username}_{CALC_SPREIZUNG}"
        self.entity_id = "sensor.es_hp_spreizung"
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
    _attr_translation_key = "thermische_leistung"
    # Klartext mit wechselndem Messwert - gehoert nicht in jeden Recorder-Eintrag
    _unrecorded_attributes = frozenset({"flow_quelle"})
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
        flow_entity: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{username}_{CALC_THERM_LEISTUNG}"
        self.entity_id = "sensor.es_hp_thermische_leistung"
        self._attr_device_info = device_info
        self._flow_heating = flow_rate_heating
        self._flow_dhw = flow_rate_dhw
        self._mode_source = mode_source
        self._hass = hass
        self._dhw_margin_k = dhw_margin_k
        self._flow_entity = flow_entity

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data or {}
        mode, _ = _resolve_betriebsart(
            self._hass, self._mode_source, data, self._dhw_margin_k
        )
        live, _ = _live_flow(self._hass, self._flow_entity)
        leistung = thermische_leistung_w(
            data, mode, self._flow_heating, self._flow_dhw, live
        )
        return None if leistung is None else round(leistung, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "flow_rate_heating_m3h": self._flow_heating,
            "flow_rate_dhw_m3h": self._flow_dhw,
            "flow_entity": self._flow_entity,
            "flow_quelle": _live_flow(self._hass, self._flow_entity)[1],
            "mode_source": self._mode_source,
            "resolved_mode": _resolve_betriebsart(
                self._hass, self._mode_source, self.coordinator.data, self._dhw_margin_k
            )[0],
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
    _attr_translation_key = "aktueller_cop"
    _unrecorded_attributes = frozenset({"flow_quelle"})
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
        flow_entity: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{username}_{CALC_COP}"
        self.entity_id = "sensor.es_hp_aktueller_cop"
        self._attr_device_info = device_info
        self._flow_heating = flow_rate_heating
        self._flow_dhw = flow_rate_dhw
        self._power_entity = power_entity
        self._mode_source = mode_source
        self._hass = hass
        self._dhw_margin_k = dhw_margin_k
        self._flow_entity = flow_entity
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

        mode, _ = _resolve_betriebsart(
            self._hass, self._mode_source, data, self._dhw_margin_k
        )
        live, _ = _live_flow(self._hass, self._flow_entity)
        active_flow = _active_flow_rate(
            mode, self._flow_heating, self._flow_dhw, live
        )
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

        therm_w = thermische_leistung_w(
            data, mode, self._flow_heating, self._flow_dhw, live
        )
        if therm_w is None or therm_w <= 0:
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
            "flow_entity": self._flow_entity,
            "flow_quelle": _live_flow(self._hass, self._flow_entity)[1],
            "mode_source": self._mode_source,
            "resolved_mode": _resolve_betriebsart(
                self._hass, self._mode_source, self.coordinator.data, self._dhw_margin_k
            )[0],
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
    _attr_translation_key = "betriebsart"
    # Diagnose-Attribute, die sich bei jedem Abruf aendern: Ohne Ausschluss
    # schrieb der Recorder jede Minute einen neuen, grossen Attributsatz.
    _unrecorded_attributes = frozenset({
        "api_response_meta",
        "begruendung",
        "par1_roh",
        "abgeleitet_aus_eigenen_werten",
        "vorlauf_c",
        "ruecklauf_c",
        "wassertemperatur_tup_c",
        "heizwasser_tc_c",
        "kompressor_hz",
    })
    _attr_device_class = "enum"
    # Zustands-Schluessel statt deutscher Texte; Anzeige ueber
    # entity.sensor.betriebsart.state.<schluessel>
    _attr_options = BETRIEBSART_STATE_OPTIONS
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
        self.entity_id = "sensor.es_hp_betriebsart"
        self._attr_device_info = device_info
        self._mode_source = mode_source
        self._hass = hass
        self._dhw_margin_k = dhw_margin_k

    @property
    def native_value(self) -> str | None:
        # Intern bleibt die Betriebsart der deutsche kanonische Wert (mode.py,
        # flow.py, Tests). Erst hier wird er zum uebersetzbaren Schluessel.
        modus = _resolve_betriebsart(
            self._hass, self._mode_source, self.coordinator.data, self._dhw_margin_k
        )[0]
        return BETRIEBSART_STATE_KEYS.get(modus)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        modus, begruendung = _resolve_betriebsart(
            self._hass, self._mode_source, data, self._dhw_margin_k
        )
        aus_par1, _ = _betriebsart_aus_par1(data)
        abgeleitet, _ = _derive_betriebsart(data, self._dhw_margin_k)
        quelle = ("Geräteangabe par1" if aus_par1 is not None
                  else ("externe Entity" if self._mode_source
                        and _mode_from_source(self._hass, self._mode_source) != "Unbekannt"
                        else "eigene Werte"))

        attrs: dict[str, Any] = {
            "quelle": quelle,
            "begruendung": begruendung,
            "par1_roh": data.get("par1"),
            "abgeleitet_aus_eigenen_werten": abgeleitet,
            "dhw_margin_k": self._dhw_margin_k,
            "vorlauf_c": data.get("par4"),
            "ruecklauf_c": data.get("par5"),
            # par6 ist Tup (Rohrtemperatur), par8 das Heizwasser im Puffer -
            # Letzteres ist seit v3.0.0 der Bezug der Ableitung.
            "wassertemperatur_tup_c": data.get("par6"),
            "heizwasser_tc_c": data.get("par8"),
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
    _attr_translation_key = "leistung_elektrisch"
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
        self.entity_id = "sensor.es_hp_leistung_elektrisch"
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


# ─────────────────────────────────────────────────────────────────────────────
# Stammdaten und Sicherungsstand  (v3.0.0)
# ─────────────────────────────────────────────────────────────────────────────

class StammdatenSensor(CoordinatorEntity[ESHeatpumpCoordinator], SensorEntity):
    """Modell, Seriennummern, Garantie und Installateur an einer Stelle.

    Der Zustand ist das Modell - das ist die Angabe, die man in einer Karte
    sehen will. Alles Uebrige haengt als Attribut daran: beide Seriennummern,
    MAC, Inbetriebnahme, Garantieende samt Restlaufzeit in Jahren,
    Installateur und Standort.

    Warum das eine eigene Entity verdient: Diese Angaben stehen sonst auf einem
    Aufkleber hinter der Verkleidung und in einer E-Mail von 2024. Im
    Garantiefall braucht man sie in genau dem Moment, in dem man nicht in den
    Heizungskeller kommt.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "anlagendaten"
    _attr_icon = "mdi:identifier"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_info: DeviceInfo, username: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{username}_stammdaten"
        self.entity_id = "sensor.es_hp_anlagendaten"
        self._attr_device_info = device_info

    @property
    def native_value(self) -> str | None:
        return self.coordinator.stammdaten.modell or "unbekannt"

    @property
    def available(self) -> bool:
        return True   # Stammdaten ueberdauern einen Abrufausfall

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self.coordinator.stammdaten
        attribute: dict[str, Any] = {
            "modell": s.modell,
            "seriennummer_aussengeraet": s.seriennummer_aussengeraet or s.seriennummer,
            "seriennummer_innengeraet": s.seriennummer_innengeraet,
            "artikelnummer": s.artikelnummer,
            "mac": s.mac,
            "portal_kennung": f"mn={s.mn}, devid={s.devid}" if s.mn else None,
            "inbetriebnahme": s.inbetriebnahme,
            "garantie_bis": s.garantie_bis,
            "installateur": s.installateur,
            "besitzer": s.besitzer,
            "standort": s.standort,
            "im_portal_angelegt": s.angelegt_am,
            "im_portal_geaendert": s.zuletzt_geaendert,
        }
        rest = s.garantie_restjahre
        if rest is not None:
            attribute["garantie_restjahre"] = rest
            attribute["garantie_aktiv"] = rest > 0
        return {k: v for k, v in attribute.items() if v is not None}


class SicherungenSensor(CoordinatorEntity, SensorEntity):
    """Wie viele Konfigurationssicherungen vorliegen und wie alt die juengste ist."""

    _attr_has_entity_name = True
    _attr_translation_key = "konfigurationssicherungen"
    # Die Liste der letzten zehn Sicherungen ist gross und steht ohnehin in
    # der Sicherungsablage - nicht in die Recorder-Historie.
    _unrecorded_attributes = frozenset({"sicherungen"})
    _attr_icon = "mdi:content-save-cog-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, settings_coordinator, device_info: DeviceInfo, username: str) -> None:
        super().__init__(settings_coordinator)
        self._attr_unique_id = f"{DOMAIN}_{username}_sicherungen"
        self.entity_id = "sensor.es_hp_konfigurationssicherungen"
        self._attr_device_info = device_info

    @property
    def native_value(self) -> int:
        return len(self.coordinator.ablage.alle)

    @property
    def available(self) -> bool:
        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ablage = self.coordinator.ablage
        neueste = ablage.neueste
        attribute: dict[str, Any] = {
            "anzahl": len(ablage.alle),
            "schreibzugriff_aktiv": getattr(self.coordinator, "schreiben_erlaubt", None),
        }
        if neueste is not None:
            attribute.update(
                letzte_sicherung=neueste.zeitpunkt,
                letzte_kennung=neueste.id,
                letzter_anlass=neueste.anlass,
                letzte_bezeichnung=neueste.label,
                letzter_grund=neueste.grund,
                pruefsumme=neueste.pruefsumme,
                gesicherte_werte=neueste.anzahl,
            )
            if self.coordinator.data:
                from .backup import pruefsumme_von
                attribute["stand_unveraendert"] = (
                    pruefsumme_von(self.coordinator.data) == neueste.pruefsumme
                )
        # Die letzten zehn Staende als Liste - genug fuer eine Karte, ohne die
        # Attributtabelle zu sprengen.
        attribute["sicherungen"] = [s.kurzfassung() for s in ablage.alle[:10]]
        return {k: v for k, v in attribute.items() if v is not None}


# ─────────────────────────────────────────────────────────────────────────────
# Energiezaehler fuer die Auswertungsseite
# ─────────────────────────────────────────────────────────────────────────────
#
# Die Rechnung steht HA-frei in energy.py. Hier stehen nur die Anbindung an
# Zustandsaenderungen und Portalabrufe sowie die Entities, deren Zaehlerstaende
# die Langzeitstatistik von Home Assistant zu Tag/Woche/Monat/Jahr verdichtet.

# Takt, in dem die elektrische Leistung auch ohne Zustandsaenderung
# fortgeschrieben wird. Ein Shelly meldet bei gleichbleibender Last mitunter
# minutenlang nichts - ohne Takt fiele so ein Intervall unter die Lueckenregel.
_TAKT_ELEKTRISCH = timedelta(minutes=1)

# Mindestabstand zwischen zwei Zustandsschreibungen der elektrischen Zaehler.
# Ein Shelly meldet mitunter jede Sekunde; jede Meldung als drei neue Zustaende
# in den Recorder zu schreiben, blaehte die Datenbank auf. Gerechnet wird
# trotzdem bei jeder Meldung - nur das Schreiben wird gebuendelt, der Takt oben
# holt Liegengebliebenes spaetestens nach einer Minute nach.
_MIN_SCHREIBABSTAND_ELEKTRISCH_S = 55.0


class EnergieBilanz:
    """Haelt die Zaehler einer Anlage und versorgt sie mit Messpunkten."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: ESHeatpumpCoordinator,
        power_entity: str | None,
        mode_source: str | None,
        dhw_margin_k: float,
        flow_heating: float,
        flow_dhw: float,
        flow_entity: str | None,
        energy_entity: str | None = None,
    ) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.power_entity = power_entity
        # Stromzaehler (kWh, v4.0.1): Ist er gesetzt, schreiben dessen
        # Zaehlerstands-Zuwaechse die elektrischen Zaehler fort, und die
        # Leistung wird dafuer nicht mehr integriert.
        self.energy_entity = energy_entity
        self._mode_source = mode_source
        self._dhw_margin_k = dhw_margin_k
        self._flow_heating = flow_heating
        self._flow_dhw = flow_dhw
        self._flow_entity = flow_entity
        self.zaehler: dict[str, EnergieZaehler] = {
            # Der Zustand der Strommess-Entity gilt, bis er sich aendert
            ART_ELEKTRISCH: EnergieZaehler(MAX_LUECKE_ELEKTRISCH_S, METHODE_LINKS),
            # Portalwerte sind Stichproben eines stetigen Verlaufs
            ART_THERMISCH: EnergieZaehler(MAX_LUECKE_THERMISCH_S, METHODE_TRAPEZ),
        }
        self.verdichter = VerdichterZaehler(MAX_LUECKE_VERDICHTER_S)
        self.folger = ZaehlerstandFolger(self.zaehler[ART_ELEKTRISCH])
        self._entities: list[SensorEntity] = []
        self._zuletzt_geschrieben: dict[str, float] = {}
        self._ausstehend = False

    @property
    def elektrisch_quelle(self) -> str | None:
        """Entity, aus der die elektrischen Zaehler gespeist werden."""
        return self.energy_entity or self.power_entity

    # -- Entities ------------------------------------------------------
    def anmelden(self, entity: SensorEntity) -> None:
        self._entities.append(entity)

    def abmelden(self, entity: SensorEntity) -> None:
        if entity in self._entities:
            self._entities.remove(entity)

    @callback
    def _schreibe(self, nur_art: str | None = None) -> None:
        for entity in self._entities:
            if nur_art is not None and getattr(entity, "art", None) != nur_art:
                continue
            if entity.hass is not None:
                entity.async_write_ha_state()

    # -- Messpunkte ----------------------------------------------------
    def _betriebsart(self) -> str:
        return _resolve_betriebsart(
            self.hass, self._mode_source, self.coordinator.data, self._dhw_margin_k
        )[0]

    @staticmethod
    def _jetzt() -> float:
        return dt_util.utcnow().timestamp()

    @callback
    def _elektrisch_messen(self) -> None:
        jetzt = self._jetzt()
        if self.energy_entity:
            state = self.hass.states.get(self.energy_entity)
            stand = None
            if state is not None:
                stand = energie_in_kwh(
                    state.state, state.attributes.get("unit_of_measurement")
                )
            kwh = self.folger.messpunkt(
                jetzt, stand, kategorie_von(self._betriebsart())
            )
        else:
            state = self.hass.states.get(self.power_entity) if self.power_entity else None
            leistung = None
            if state is not None:
                leistung = leistung_in_w(
                    state.state, state.attributes.get("unit_of_measurement")
                )
            kwh = self.zaehler[ART_ELEKTRISCH].messpunkt(
                jetzt, leistung, kategorie_von(self._betriebsart())
            )
        if kwh > 0:
            self._ausstehend = True
        if not self._ausstehend:
            return
        zuletzt = self._zuletzt_geschrieben.get(ART_ELEKTRISCH)
        if zuletzt is not None and 0 <= jetzt - zuletzt < _MIN_SCHREIBABSTAND_ELEKTRISCH_S:
            return
        self._zuletzt_geschrieben[ART_ELEKTRISCH] = jetzt
        self._ausstehend = False
        self._schreibe(ART_ELEKTRISCH)

    @callback
    def _bei_leistungsaenderung(self, _event: Event) -> None:
        self._elektrisch_messen()

    @callback
    def _bei_takt(self, _now) -> None:
        self._elektrisch_messen()

    @callback
    def _bei_abruf(self) -> None:
        """Nach jedem Portalabruf: thermische Energie und Verdichter."""
        if not self.coordinator.last_update_success or not self.coordinator.data:
            return
        data = self.coordinator.data
        t = self._jetzt()
        modus = self._betriebsart()
        live, _ = _live_flow(self.hass, self._flow_entity)
        leistung = thermische_leistung_w(
            data, modus, self._flow_heating, self._flow_dhw, live
        )
        kwh = self.zaehler[ART_THERMISCH].messpunkt(t, leistung, kategorie_von(modus))
        verdichter = self.verdichter.messpunkt(t, data.get("par20"))
        if kwh > 0:
            self._schreibe(ART_THERMISCH)
        if verdichter:
            self._schreibe("verdichter")

    @callback
    def async_starte(self):
        """Startet die Beobachtung; liefert die Abmeldefunktion."""
        abmelden = [self.coordinator.async_add_listener(self._bei_abruf)]
        quelle = self.elektrisch_quelle
        if quelle:
            abmelden.append(
                async_track_state_change_event(
                    self.hass, [quelle], self._bei_leistungsaenderung
                )
            )
            abmelden.append(
                async_track_time_interval(self.hass, self._bei_takt, _TAKT_ELEKTRISCH)
            )
            self._elektrisch_messen()

        @callback
        def _stopp() -> None:
            for fn in abmelden:
                fn()

        return _stopp


class _BilanzSensor(RestoreSensor):
    """Gemeinsame Grundlage der Zaehler-Entities."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    art = ""

    def __init__(
        self, bilanz: EnergieBilanz, device_info: DeviceInfo, username: str, slug: str
    ) -> None:
        self._bilanz = bilanz
        self._attr_translation_key = slug
        self._attr_unique_id = f"{DOMAIN}_{username}_calc_{slug}"
        self.entity_id = f"sensor.es_hp_{slug}"
        self._attr_device_info = device_info

    def _uebernehme(self, wert: Any) -> None:
        raise NotImplementedError

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        letzte = await self.async_get_last_sensor_data()
        if letzte is not None and letzte.native_value is not None:
            # Zaehlerstand fortsetzen - nie zuruecksetzen, sonst entstuende in
            # der Statistik ein Sprung, den HA als Zaehlertausch werten muesste.
            self._uebernehme(letzte.native_value)
        self._bilanz.anmelden(self)

    async def async_will_remove_from_hass(self) -> None:
        self._bilanz.abmelden(self)
        await super().async_will_remove_from_hass()


class EnergieZaehlerSensor(_BilanzSensor):
    """Elektrische oder thermische Energie (kWh), gesamt oder je Betriebsart."""

    _attr_native_unit_of_measurement = "kWh"
    _attr_device_class = "energy"
    _attr_suggested_display_precision = 2
    # Basis des Stromzaehlers: aendert sich bei jedem Schreiben und dient nur
    # der Wiederherstellung nach einem Neustart. Die Wiederherstellung liest
    # den gespeicherten Zustand (restore_state), nicht den Recorder - der
    # Ausschluss schadet ihr also nicht.
    _unrecorded_attributes = frozenset({"zaehlerstand_kwh", "zaehlerstand_zeit"})

    def __init__(
        self,
        bilanz: EnergieBilanz,
        device_info: DeviceInfo,
        username: str,
        slug: str,
        art: str,
        teil: str,
    ) -> None:
        super().__init__(bilanz, device_info, username, slug)
        self.art = art
        self._teil = teil
        self._attr_icon = (
            "mdi:lightning-bolt" if art == ART_ELEKTRISCH else "mdi:fire"
        )

    def _uebernehme(self, wert: Any) -> None:
        self._bilanz.zaehler[self.art].uebernehme(self._teil, wert)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Basis des Stromzaehlers wiederherstellen (nur der Gesamtzaehler traegt
        # sie), damit der Verbrauch waehrend eines Neustarts mitgezaehlt wird.
        # Nur, wenn es noch dieselbe Zaehler-Entity ist.
        bilanz = self._bilanz
        if self.art != ART_ELEKTRISCH or self._teil != GESAMT or not bilanz.energy_entity:
            return
        letzter = await self.async_get_last_state()
        if letzter is None:
            return
        attrs = letzter.attributes
        if attrs.get("energy_entity") == bilanz.energy_entity:
            bilanz.folger.setze_basis(
                attrs.get("zaehlerstand_kwh"), attrs.get("zaehlerstand_zeit")
            )

    @property
    def available(self) -> bool:
        # Ohne Strommessung gibt es keinen elektrischen Zaehler
        if self.art == ART_ELEKTRISCH:
            return self._bilanz.elektrisch_quelle is not None
        return True

    @property
    def native_value(self) -> float:
        return round(self._bilanz.zaehler[self.art].summen[self._teil], 4)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {"teil": self._teil}
        if self.art == ART_ELEKTRISCH:
            bilanz = self._bilanz
            attrs["power_entity"] = bilanz.power_entity
            if bilanz.energy_entity:
                attrs["energy_entity"] = bilanz.energy_entity
                if self._teil == GESAMT and bilanz.folger.basis is not None:
                    attrs["zaehlerstand_kwh"] = round(bilanz.folger.basis, 6)
                    attrs["zaehlerstand_zeit"] = bilanz.folger.basis_t
        return attrs


class VerdichterStartsSensor(_BilanzSensor):
    """Anzahl der Verdichterstarts (Taktung)."""

    _attr_translation_key = "verdichter_starts"
    _attr_icon = "mdi:counter"
    art = "verdichter"

    def __init__(self, bilanz: EnergieBilanz, device_info: DeviceInfo, username: str) -> None:
        super().__init__(bilanz, device_info, username, self._attr_translation_key)

    def _uebernehme(self, wert: Any) -> None:
        self._bilanz.verdichter.uebernehme(starts=wert)

    @property
    def native_value(self) -> int:
        return self._bilanz.verdichter.starts


class VerdichterLaufzeitSensor(_BilanzSensor):
    """Laufzeit des Verdichters (h)."""

    _attr_native_unit_of_measurement = "h"
    _attr_device_class = "duration"
    _attr_translation_key = "verdichter_laufzeit"
    _attr_icon = "mdi:timer-outline"
    _attr_suggested_display_precision = 1
    art = "verdichter"

    def __init__(self, bilanz: EnergieBilanz, device_info: DeviceInfo, username: str) -> None:
        super().__init__(bilanz, device_info, username, self._attr_translation_key)

    def _uebernehme(self, wert: Any) -> None:
        self._bilanz.verdichter.uebernehme(laufzeit_h=wert)

    @property
    def native_value(self) -> float:
        return round(self._bilanz.verdichter.laufzeit_h, 4)
