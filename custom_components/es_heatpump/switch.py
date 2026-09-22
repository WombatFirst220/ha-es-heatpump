"""Ein/Aus-Einstellungen der Anlage als Schalter."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENABLE_WRITES, DEFAULT_ENABLE_WRITES, DOMAIN
from .device import baue_device_info
from .entity import ESHeatpumpSettingEntity
from .settings import KIND_SWITCH, SETTINGS

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
        ESHeatpumpSwitch(koord, s, info, username, schreiben)
        for s in SETTINGS.values()
        if s.kind == KIND_SWITCH
    )


class ESHeatpumpSwitch(ESHeatpumpSettingEntity, SwitchEntity):
    """Eine Ein/Aus-Einstellung."""

    _plattform = "switch"

    @property
    def is_on(self) -> bool | None:
        wert = self.roh_wert
        return None if wert is None else bool(int(wert))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_setze(1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_setze(0)
