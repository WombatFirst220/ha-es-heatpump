"""Gemeinsame Basis der Bedien-Entities (Zahl, Auswahl, Schalter).

Alle Konfigurations-Entities tragen das Praefix ``es_hp_cfg_``. Das ist kein
Schoenheitsmerkmal, sondern eine Schutzmassnahme: Das Portal fuehrt ``parXX``
in zwei voellig verschiedenen Bedeutungen (Messwerte gegen Einstellungen), und
ohne getrennte Namensraeume waere ``sensor.es_hp_par1`` und
``switch.es_hp_par1`` dasselbe Wort fuer zwei Dinge. Siehe den Kopf von
``settings.py``.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .settings import Setting
from .settings_coordinator import ESHeatpumpSettingsCoordinator

_LOGGER = logging.getLogger(__name__)


class ESHeatpumpSettingEntity(CoordinatorEntity[ESHeatpumpSettingsCoordinator]):
    """Eine bedienbare Einstellung der Waermepumpe."""

    _attr_has_entity_name = False
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: ESHeatpumpSettingsCoordinator,
        setting: Setting,
        device_info: DeviceInfo,
        username: str,
        schreiben_erlaubt: bool,
    ) -> None:
        super().__init__(coordinator)
        self.setting = setting
        self._schreiben_erlaubt = schreiben_erlaubt
        self._attr_unique_id = f"{DOMAIN}_{username}_cfg_{setting.par}"
        self._attr_name = f"WP {setting.group}: {setting.name}"
        self.entity_id = f"{self._plattform}.es_hp_{setting.slug}"
        self._attr_device_info = device_info
        self._attr_entity_registry_enabled_default = setting.enabled_default

    # Von den Unterklassen gesetzt
    _plattform = "sensor"

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
            and self.setting.par in (self.coordinator.data or {})
        )

    @property
    def roh_wert(self) -> float | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self.setting.par)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "portal_feld": self.setting.par,
            "portal_bezeichnung": self.setting.portal_label,
            "gruppe": self.setting.group,
            "schreiben_erlaubt": self._schreiben_erlaubt,
        }

    async def _async_setze(self, wert: Any) -> None:
        """Schreibt einen Wert - nach Freigabepruefung und Katalogpruefung."""
        if not self._schreiben_erlaubt:
            raise Schreibsperre(
                f"Der Schreibzugriff ist abgeschaltet. {self.setting.name} wurde "
                "nicht geändert. Einschalten in den Einstellungen der Integration "
                "unter „Schreibzugriff auf die Anlage erlauben“."
            )
        geprueft = self.setting.validate(wert)
        await self.coordinator.async_setze(self.setting.par, geprueft)


class Schreibsperre(HomeAssistantError):
    """Der Schreibzugriff ist in den Optionen nicht freigegeben.

    Eigene Klasse und von ``HomeAssistantError`` abgeleitet, damit die Meldung
    in der Oberflaeche erscheint und erklaert, *warum* nichts passiert ist -
    ein stiller Fehlschlag waere bei einer Heizung die schlechteste aller
    Antworten.
    """
