"""Auswahllisten der Anlagenkonfiguration."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENABLE_WRITES, DEFAULT_ENABLE_WRITES, DOMAIN
from .device import baue_device_info
from .entity import ESHeatpumpSettingEntity
from .settings import KIND_SELECT, SETTINGS

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
        ESHeatpumpSelect(koord, s, info, username, schreiben)
        for s in SETTINGS.values()
        if s.kind == KIND_SELECT
    )


class ESHeatpumpSelect(ESHeatpumpSettingEntity, SelectEntity):
    """Eine Auswahl mit den Bezeichnungen, die das Portal selbst verwendet."""

    _plattform = "select"

    def __init__(self, coordinator, setting, device_info, username, schreiben) -> None:
        super().__init__(coordinator, setting, device_info, username, schreiben)
        self._nach_text = dict(setting.options)
        self._nach_zahl = {v: k for k, v in setting.options.items()}
        self._attr_options = list(setting.options.values())

    @property
    def current_option(self) -> str | None:
        wert = self.roh_wert
        if wert is None:
            return None
        return self._nach_text.get(int(wert))

    async def async_select_option(self, option: str) -> None:
        if option not in self._nach_zahl:
            raise ValueError(
                f"{option!r} ist keine gültige Auswahl für {self.setting.name}"
            )
        await self._async_setze(self._nach_zahl[option])
