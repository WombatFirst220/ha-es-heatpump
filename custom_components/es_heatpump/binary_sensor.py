"""Binaersensoren der Waermepumpe (v4.1.0).

* ``verdichter``          - Verdichter laeuft (par20 > 0)
* ``abtauen``             - Abtauvorgang (aufgeloeste Betriebsart "Entfrosten")
* ``warmwasserbereitung`` - Umschaltventil am Warmwasserspeicher (Betriebsart
  Brauchwasser, Brauchwasser + Heizen, Brauchwasser + Kuehlen)
* ``takten``              - Verdichter taktet (Schwellen in energy.py)

Die Betriebsart kommt aus ``mode.resolve_betriebsart`` - derselben Rechnung
samt Zwischenspeicher, die auch die Sensoren nutzen. Die Takt-Erkennung liest
den Verdichter-Zaehler der gemeinsamen ``EnergieBilanz`` (sensor.py), damit
Starts nicht doppelt gezaehlt werden.

Entity-IDs ``binary_sensor.es_hp_<slug>``, unique_id
``es_heatpump_<benutzer>_<slug>``, Namen aus ``entity.binary_sensor.<slug>``.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ESHeatpumpCoordinator
from .device import baue_device_info
from .energy import TAKT_MAX_STARTS_JE_STUNDE, TAKT_MIN_LAUFZEIT_MIN, TAKT_ZYKLEN
from .mode import (
    ist_entfrosten,
    ist_warmwasserbereitung,
    resolve_betriebsart,
    verdichter_laeuft,
)
from .sensor import EnergieBilanz, bilanz_fuer, messoptionen

_LOGGER = logging.getLogger(__name__)

# Nur Lesen aus den Koordinatoren
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    daten = hass.data[DOMAIN][entry.entry_id]
    coordinator: ESHeatpumpCoordinator = daten["api"]
    username = entry.data[CONF_USERNAME]
    settings = daten.get("settings")
    info = baue_device_info(
        username, coordinator._base_url, coordinator.stammdaten,
        settings.data if settings is not None else None,
    )
    o = messoptionen(entry)
    bilanz = bilanz_fuer(hass, entry)
    async_add_entities([
        VerdichterBinaerSensor(coordinator, info, username),
        AbtauenBinaerSensor(coordinator, info, username, hass, o["mode_source"], o["dhw_margin_k"]),
        WarmwasserBinaerSensor(coordinator, info, username, hass, o["mode_source"], o["dhw_margin_k"]),
        TaktenBinaerSensor(bilanz, coordinator, info, username),
    ])


class _Basis(CoordinatorEntity[ESHeatpumpCoordinator], BinarySensorEntity):
    """Gemeinsame Grundlage: Messwert-Koordinator, feste ID aus dem Slug."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _slug = ""

    def __init__(
        self, coordinator: ESHeatpumpCoordinator, device_info: DeviceInfo, username: str
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{username}_{self._slug}"
        self.entity_id = f"binary_sensor.es_hp_{self._slug}"
        self._attr_device_info = device_info


class VerdichterBinaerSensor(_Basis):
    """Verdichter laeuft (Frequenz par20 > 0)."""

    _slug = "verdichter"
    _attr_translation_key = "verdichter"
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_icon = "mdi:heat-pump-outline"

    @property
    def is_on(self) -> bool | None:
        return verdichter_laeuft(self.coordinator.data)


class _BetriebsartBasis(_Basis):
    """Binaersensor, der aus der aufgeloesten Betriebsart folgt."""

    def __init__(
        self,
        coordinator: ESHeatpumpCoordinator,
        device_info: DeviceInfo,
        username: str,
        hass: HomeAssistant,
        mode_source: str | None,
        dhw_margin_k: float,
    ) -> None:
        super().__init__(coordinator, device_info, username)
        self._hass = hass
        self._mode_source = mode_source
        self._dhw_margin_k = dhw_margin_k

    def _betriebsart(self) -> str:
        return resolve_betriebsart(
            self._hass, self._mode_source, self.coordinator.data, self._dhw_margin_k
        )[0]


class AbtauenBinaerSensor(_BetriebsartBasis):
    """Abtauvorgang: Betriebsart "Entfrosten" (inkl. mode.ist_abtauen)."""

    _slug = "abtauen"
    _attr_translation_key = "abtauen"
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_icon = "mdi:snowflake-melt"

    @property
    def is_on(self) -> bool | None:
        return ist_entfrosten(self._betriebsart())


class WarmwasserBinaerSensor(_BetriebsartBasis):
    """Warmwasserbereitung laut Betriebsart."""

    _slug = "warmwasserbereitung"
    _attr_translation_key = "warmwasserbereitung"
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_icon = "mdi:water-boiler"

    @property
    def is_on(self) -> bool | None:
        return ist_warmwasserbereitung(self._betriebsart())


class TaktenBinaerSensor(BinarySensorEntity):
    """Verdichter taktet.

    An: mehr als ``TAKT_MAX_STARTS_JE_STUNDE`` Starts in der letzten Stunde
    ODER mittlere Laufzeit der letzten ``TAKT_ZYKLEN`` Zyklen unter
    ``TAKT_MIN_LAUFZEIT_MIN`` Minuten. Begruendung der Schwellen in energy.py.

    Bewusst keine CoordinatorEntity: Der Zustand wird von der EnergieBilanz
    nach jedem Abruf geschrieben, NACH dem Fortschreiben des Verdichter-
    Zaehlers (``art = "takt"``). Ein eigener Koordinator-Listener koennte vor
    dem der Bilanz laufen und zeigte dann den Stand des vorigen Abrufs.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "takten"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:sine-wave"
    # Aendern sich nur mit Starts/Stopps; Schwellen sind Konstanten
    _unrecorded_attributes = frozenset({
        "schwelle_starts_je_stunde", "schwelle_laufzeit_min", "zyklen_fuer_mittel",
    })
    art = "takt"

    def __init__(
        self,
        bilanz: EnergieBilanz,
        coordinator: ESHeatpumpCoordinator,
        device_info: DeviceInfo,
        username: str,
    ) -> None:
        self._bilanz = bilanz
        self._coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_{username}_takten"
        self.entity_id = "binary_sensor.es_hp_takten"
        self._attr_device_info = device_info

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._bilanz.anmelden(self)

    async def async_will_remove_from_hass(self) -> None:
        self._bilanz.abmelden(self)
        await super().async_will_remove_from_hass()

    @property
    def available(self) -> bool:
        return bool(self._coordinator.last_update_success)

    @property
    def is_on(self) -> bool:
        return self._bilanz.verdichter.taktet(self._bilanz.jetzt())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        v = self._bilanz.verdichter
        mittel = v.mittlere_laufzeit_min()
        return {
            "starts_letzte_stunde": v.starts_seit(self._bilanz.jetzt()),
            "mittlere_laufzeit_min": None if mittel is None else round(mittel, 1),
            "schwelle_starts_je_stunde": TAKT_MAX_STARTS_JE_STUNDE,
            "schwelle_laufzeit_min": TAKT_MIN_LAUFZEIT_MIN,
            "zyklen_fuer_mittel": TAKT_ZYKLEN,
        }
