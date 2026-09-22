"""Zahlenwerte der Anlagenkonfiguration als bedienbare Entities."""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENABLE_WRITES, DEFAULT_ENABLE_WRITES, DOMAIN
from .device import baue_device_info
from .entity import ESHeatpumpSettingEntity
from .settings import KIND_NUMBER, SETTINGS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    daten = hass.data[DOMAIN][entry.entry_id]
    koord = daten.get("settings")
    if koord is None:
        return
    username = entry.data[CONF_USERNAME]
    schreiben = bool(
        entry.options.get(
            CONF_ENABLE_WRITES, entry.data.get(CONF_ENABLE_WRITES, DEFAULT_ENABLE_WRITES)
        )
    )
    info = baue_device_info(
        username, daten["api"]._base_url, daten["api"].stammdaten, koord.data
    )
    async_add_entities(
        ESHeatpumpNumber(koord, s, info, username, schreiben)
        for s in SETTINGS.values()
        if s.kind == KIND_NUMBER
    )


class ESHeatpumpNumber(ESHeatpumpSettingEntity, NumberEntity):
    """Ein Zahlenwert, den das Portal zum Bearbeiten anbietet."""

    _plattform = "number"
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, setting, device_info, username, schreiben) -> None:
        super().__init__(coordinator, setting, device_info, username, schreiben)
        self._attr_native_min_value = (
            setting.minimum if setting.minimum is not None else -999
        )
        self._attr_native_max_value = (
            setting.maximum if setting.maximum is not None else 999
        )
        self._attr_native_step = setting.step
        self._attr_native_unit_of_measurement = setting.unit
        if setting.device_class:
            self._attr_device_class = setting.device_class

    @property
    def native_value(self) -> float | None:
        return self.roh_wert

    async def async_set_native_value(self, value: float) -> None:
        await self._async_setze(value)
