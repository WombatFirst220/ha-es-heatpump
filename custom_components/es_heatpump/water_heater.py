"""Warmwasserspeicher als water_heater-Entity (v4.1.0).

``water_heater.es_hp_warmwasser`` fasst zusammen, was sonst auf zwei Entities
verteilt ist:

* Ist-Temperatur  = Messwert par7 (Warmwasser TW, Messwert-Koordinator)
* Soll-Temperatur = Einstellung par55 (Warmwasser Solltemperatur,
  Konfigurations-Koordinator; Bereich aus dem Katalog in settings.py)

Achtung Namensraum: par7 ist ein Messwert, par55 eine Einstellung - zwei
verschiedene parXX-Raeume, siehe Kopf von settings.py.

Schreiben geht ueber denselben Weg wie ``number.es_hp_cfg_par55``
(``entity.async_schreibe_einstellung``: Schreibsperre, Katalogpruefung,
Sicherung vor dem Schreiben). Ohne freigegebenen Schreibzugriff bietet die
Entity das Setzen der Solltemperatur gar nicht erst an.

Kompatibilitaet: Neuere HA-Versionen fuehren die Temperaturen als
``native_*``-Eigenschaften und melden die alten Namen als veraltet. Welche
Variante gilt, wird beim Import an der Basisklasse erkannt.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.water_heater import (
    STATE_HEAT_PUMP,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, CONF_USERNAME, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ENABLE_WRITES, DEFAULT_ENABLE_WRITES, DOMAIN, TEMP_SENTINEL
from .coordinator import ESHeatpumpCoordinator
from .device import baue_device_info
from .entity import async_schreibe_einstellung
from .settings import SETTINGS, Setting
from .settings_coordinator import ESHeatpumpSettingsCoordinator

_LOGGER = logging.getLogger(__name__)

# Schreibzugriffe nacheinander - wie number.py
PARALLEL_UPDATES = 1

PAR_IST = "par7"        # Messwert: Warmwasser TW
PAR_SOLL = "par55"      # Einstellung: Warmwasser Solltemperatur

# Neuere HA-Versionen: native_current_temperature usw. (alte Namen veraltet)
_NATIV = hasattr(WaterHeaterEntity, "native_current_temperature")


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    daten = hass.data[DOMAIN][entry.entry_id]
    koord: ESHeatpumpCoordinator = daten["api"]
    settings: ESHeatpumpSettingsCoordinator | None = daten.get("settings")
    setting = SETTINGS.get(PAR_SOLL)
    if settings is None or setting is None:
        return
    username = entry.data[CONF_USERNAME]
    schreiben = bool(
        entry.options.get(
            CONF_ENABLE_WRITES, entry.data.get(CONF_ENABLE_WRITES, DEFAULT_ENABLE_WRITES)
        )
    )
    info = baue_device_info(username, koord._base_url, koord.stammdaten, settings.data)
    async_add_entities([
        ESHeatpumpWarmwasser(koord, settings, setting, info, username, schreiben)
    ])


def _zahl(wert: Any) -> float | None:
    """Gueltiger Temperaturwert oder ``None`` (auch fuer den -99-Platzhalter)."""
    if wert is None:
        return None
    try:
        zahl = float(wert)
    except (TypeError, ValueError):
        return None
    if zahl <= TEMP_SENTINEL:
        return None
    return zahl


class ESHeatpumpWarmwasser(CoordinatorEntity[ESHeatpumpCoordinator], WaterHeaterEntity):
    """Warmwasserspeicher: Ist aus par7, Soll aus der Einstellung par55."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "warmwasser"
    _attr_icon = "mdi:water-boiler"
    _attr_operation_list = [STATE_HEAT_PUMP]
    _attr_current_operation = STATE_HEAT_PUMP
    # Anzeige in Zehntelgrad wie der Messwert-Sensor par7; der Sollwert wird
    # ueber die Schrittweite auf ganze Grad beschraenkt (das Geraet nimmt nur
    # ganze Grad, siehe Setting.step).
    _attr_precision = 0.1
    if _NATIV:
        _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    else:
        _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        coordinator: ESHeatpumpCoordinator,
        settings: ESHeatpumpSettingsCoordinator,
        setting: Setting,
        device_info: DeviceInfo,
        username: str,
        schreiben_erlaubt: bool,
    ) -> None:
        super().__init__(coordinator)
        self._settings = settings
        self._setting = setting
        self._schreiben_erlaubt = schreiben_erlaubt
        self._attr_unique_id = f"{DOMAIN}_{username}_warmwasser"
        self.entity_id = "water_heater.es_hp_warmwasser"
        self._attr_device_info = device_info
        self._attr_min_temp = float(setting.minimum) if setting.minimum is not None else 25.0
        self._attr_max_temp = float(setting.maximum) if setting.maximum is not None else 75.0
        self._attr_target_temperature_step = float(setting.step or 1.0)
        # Setzen der Solltemperatur nur mit freigegebenem Schreibzugriff
        self._attr_supported_features = (
            WaterHeaterEntityFeature.TARGET_TEMPERATURE
            if schreiben_erlaubt
            else WaterHeaterEntityFeature(0)
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Auch auf den Konfigurations-Koordinator hoeren (Sollwert)
        self.async_on_remove(
            self._settings.async_add_listener(self._handle_coordinator_update)
        )

    # -- Werte ---------------------------------------------------------
    def _ist(self) -> float | None:
        return _zahl((self.coordinator.data or {}).get(PAR_IST))

    def _soll(self) -> float | None:
        return _zahl((self._settings.data or {}).get(PAR_SOLL))

    @property
    def available(self) -> bool:
        return (
            bool(self.coordinator.last_update_success)
            and bool(self._settings.last_update_success)
            and self._ist() is not None
            and self._soll() is not None
        )

    if _NATIV:
        @property
        def native_current_temperature(self) -> float | None:
            return self._ist()

        @property
        def native_target_temperature(self) -> float | None:
            return self._soll()
    else:
        @property
        def current_temperature(self) -> float | None:
            return self._ist()

        @property
        def target_temperature(self) -> float | None:
            return self._soll()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "portal_feld_ist": PAR_IST,
            "portal_feld_soll": PAR_SOLL,
            "schreiben_erlaubt": self._schreiben_erlaubt,
        }

    # -- Schreiben -----------------------------------------------------
    async def async_set_temperature(self, **kwargs: Any) -> None:
        wert = kwargs.get(ATTR_TEMPERATURE)
        if wert is None:
            return
        name = self.name if isinstance(self.name, str) else None
        await async_schreibe_einstellung(
            self._settings, self._setting, wert,
            self._schreiben_erlaubt, name or self._setting.name,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
