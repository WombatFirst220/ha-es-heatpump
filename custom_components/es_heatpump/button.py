"""Ein Knopf, der den jetzigen Konfigurationsstand sichert.

Der Dienst ``es_heatpump.sicherung_erstellen`` kann dasselbe und mehr. Aber ein
Knopf auf der Geraeteseite ist das, was man vor einem Eingriff tatsaechlich
drueckt - ein Dienstaufruf mit Formular ist es nicht.
"""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .backup import ANLASS_MANUELL
from .const import DOMAIN
from .device import baue_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    daten = hass.data[DOMAIN][entry.entry_id]
    koord = daten.get("settings")
    if koord is None:
        return
    username = entry.data[CONF_USERNAME]
    info = baue_device_info(
        username, daten["api"]._base_url, daten["api"].stammdaten, koord.data
    )
    async_add_entities([SicherungJetztButton(koord, info, username)])


class SicherungJetztButton(CoordinatorEntity, ButtonEntity):
    """„Konfiguration jetzt sichern“."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:content-save-cog"

    def __init__(self, coordinator, device_info, username: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{username}_backup_now"
        self._attr_name = "WP Konfiguration jetzt sichern"
        self.entity_id = "button.es_hp_konfiguration_sichern"
        self._attr_device_info = device_info

    async def async_press(self) -> None:
        if not self.coordinator.data:
            raise HomeAssistantError(
                "Der Konfigurationsstand ist gerade nicht bekannt - es wurde "
                "nichts gesichert. Nach dem nächsten erfolgreichen Abruf erneut "
                "versuchen."
            )
        sicherung = await self.coordinator.ablage.async_erstelle(
            dict(self.coordinator.data),
            self.coordinator.api.stammdaten.als_dict(),
            anlass=ANLASS_MANUELL,
            label="Von Hand ausgelöst",
            version=getattr(self.coordinator, "_version", ""),
        )
        _LOGGER.info(
            "ES Heatpump: Sicherung %s von Hand angelegt",
            sicherung.id if sicherung else "-",
        )
