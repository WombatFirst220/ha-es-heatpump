"""ES Heatpump integration for Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import CONF_BASE_URL, CONF_SCAN_INTERVAL, DEFAULT_BASE_URL, DEFAULT_SCAN_INTERVAL, DOMAIN, PLATFORMS
from .coordinator import ESHeatpumpCoordinator
from .dashboard import async_install_dashboard, async_remove_dashboard

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ES Heatpump from a config entry."""
    coordinator = ESHeatpumpCoordinator(
        hass=hass,
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        base_url=entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
        scan_interval=entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        ),
    )

    # First data refresh – raises ConfigEntryNotReady on failure
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Forward to sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # ── Auto-install Lovelace dashboard ──────────────────────────────────────
    # Scheduled as a background task so it never blocks the setup.
    hass.async_create_task(
        async_install_dashboard(hass),
        name="es_heatpump_install_dashboard",
    )

    # Reload when options change (e.g. scan interval updated by user)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and clean up the dashboard."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        # Only remove the dashboard when the last configured entry is removed
        if not hass.data.get(DOMAIN):
            await async_remove_dashboard(hass)

    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
