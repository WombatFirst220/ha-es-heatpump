"""Sensor platform for ES Heatpump integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DEVICE_NAME,
    DOMAIN,
    PARAMETER_SENSORS,
)
from .coordinator import ESHeatpumpCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ES Heatpump sensors from a config entry."""
    coordinator: ESHeatpumpCoordinator = hass.data[DOMAIN][entry.entry_id]
    username = entry.data[CONF_USERNAME]

    # Device info shared by all sensor entities
    device_info = DeviceInfo(
        identifiers={(DOMAIN, username)},
        name=DEVICE_NAME,
        manufacturer=DEVICE_MANUFACTURER,
        model=DEVICE_MODEL,
        configuration_url=coordinator._base_url,
    )

    entities: list[ESHeatpumpSensor] = []
    data = coordinator.data or {}

    for par_id, value in data.items():
        if value is None:
            continue  # skip parameters that didn't parse as float

        meta = PARAMETER_SENSORS.get(par_id)

        if meta:
            # Known parameter with friendly name
            friendly_name = meta["name"]
            unit = meta.get("unit")
            device_class = meta.get("device_class")
            state_class = meta.get("state_class")
            icon = meta.get("icon")
        else:
            # Unknown parameter → expose with generic name so nothing is lost
            friendly_name = f"Parameter {par_id}"
            unit = None
            device_class = None
            state_class = SensorStateClass.MEASUREMENT
            icon = "mdi:gauge"

        entities.append(
            ESHeatpumpSensor(
                coordinator=coordinator,
                device_info=device_info,
                par_id=par_id,
                friendly_name=friendly_name,
                native_unit=unit,
                device_class=device_class,
                state_class=state_class,
                icon=icon,
                username=username,
            )
        )

    _LOGGER.info(
        "ES Heatpump: creating %d sensor entities for %s",
        len(entities),
        username,
    )
    async_add_entities(entities)


class ESHeatpumpSensor(CoordinatorEntity[ESHeatpumpCoordinator], SensorEntity):
    """A single sensor entity for one heat-pump parameter."""

    _attr_has_entity_name = True
    _attr_should_poll = False  # coordinator handles polling

    def __init__(
        self,
        coordinator: ESHeatpumpCoordinator,
        device_info: DeviceInfo,
        par_id: str,
        friendly_name: str,
        native_unit: str | None,
        device_class: str | None,
        state_class: str | None,
        icon: str | None,
        username: str,
    ) -> None:
        super().__init__(coordinator)
        self._par_id = par_id
        self._attr_name = friendly_name
        self._attr_unique_id = f"{DOMAIN}_{username}_{par_id}"
        self._attr_native_unit_of_measurement = native_unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_icon = icon
        self._attr_device_info = device_info

    @property
    def native_value(self) -> float | None:
        """Return the current sensor value."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._par_id)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"parameter_id": self._par_id}
