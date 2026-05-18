"""ES Heatpump integration for Home Assistant."""
from __future__ import annotations

import logging
import re

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CALC_COP,
    CALC_ELEC_POWER,
    CALC_SPREIZUNG,
    CALC_THERM_LEISTUNG,
    CONF_BASE_URL,
    CONF_SCAN_INTERVAL,
    DEFAULT_BASE_URL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PARAMETER_SENSORS,
    PLATFORMS,
)
from .coordinator import ESHeatpumpCoordinator
from .dashboard import async_install_dashboard, async_remove_dashboard

_LOGGER = logging.getLogger(__name__)

# Matches unique_ids of the form "es_heatpump_<username>_parNN"
_UNIQUE_ID_RE = re.compile(rf"^{DOMAIN}_(.+)_par(\d+)$")


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries to the current schema version.

    v1 → v2 (2026-05-18):
        No structural change in ``entry.data`` — the new optional fields
        ``power_entity`` and ``flow_rate`` are simply absent in legacy
        entries and read via ``.get()`` with a default.  We just bump the
        version stamp so HA knows the entry is compatible.
    """
    _LOGGER.info(
        "ES Heatpump: migrating config entry from v%s to v2", entry.version
    )
    if entry.version == 1:
        hass.config_entries.async_update_entry(entry, version=2)
    return True


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

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Forward to sensor platform first.  All entities (raw `parXX` from the
    # config registry + the three freshly-created calculated sensors) are
    # registered here before we rename them in one pass.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # ── Entity-registry migration ────────────────────────────────────────
    # Renames legacy ``sensor.es_warmepumpe_*`` IDs to ``sensor.es_hp_<slug>``
    # (raw parameters AND calculated sensors), and removes orphaned entities
    # for parameters we no longer expose.  Safe to run on every startup —
    # the rename is a no-op once IDs are already correct.
    await _async_migrate_entities(hass, entry)

    # ── Auto-install Lovelace dashboard ──────────────────────────────────
    try:
        await async_install_dashboard(hass)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("ES Heatpump: dashboard install failed: %s", err)

    # Reload when options change (e.g. scan interval, flow rate, power entity)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and clean up the dashboard."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data.get(DOMAIN):
            await async_remove_dashboard(hass)

    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


# ─────────────────────────────────────────────────────────────────────────────
# Entity-ID migration
# ─────────────────────────────────────────────────────────────────────────────

async def _async_migrate_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """One-time renaming of legacy entity_ids to the new ``es_hp_*`` scheme.

    Strategy:
      1. For every parameter listed in ``PARAMETER_SENSORS``, look up the
         existing entity by ``unique_id`` and, if its ``entity_id`` doesn't
         match ``sensor.es_hp_<slug>``, rename it.  History and statistics
         move with the entity automatically.
      2. Find entities whose unique_id is ``es_heatpump_<user>_parNN`` for an
         NN that is NOT in ``PARAMETER_SENSORS`` (the orphaned ``par1`` …
         ``par100`` "Parameter parXX" leftovers from earlier plugin
         versions) and remove them.  These never carried useful data.
    """
    ent_reg = er.async_get(hass)

    # --- Step 1: rename ---------------------------------------------------
    for par_id, meta in PARAMETER_SENSORS.items():
        username = entry.data[CONF_USERNAME]
        unique_id = f"{DOMAIN}_{username}_{par_id}"
        current_id = ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id)
        if current_id is None:
            continue   # entity not yet created (will get correct id on first setup)

        target_id = f"sensor.es_hp_{meta['slug']}"
        if current_id == target_id:
            continue   # already migrated

        # Target id taken by an unrelated entity?
        clash = ent_reg.async_get(target_id)
        if clash is not None and clash.unique_id != unique_id:
            _LOGGER.warning(
                "ES Heatpump: cannot rename %s → %s (target already used by %s)",
                current_id, target_id, clash.unique_id,
            )
            continue

        _LOGGER.info("ES Heatpump: migrating %s → %s", current_id, target_id)
        ent_reg.async_update_entity(current_id, new_entity_id=target_id)

    # Also handle the three calculated sensors so their entity_ids are stable
    username = entry.data[CONF_USERNAME]
    for calc_key, target_slug in (
        (CALC_SPREIZUNG, "es_hp_spreizung"),
        (CALC_THERM_LEISTUNG, "es_hp_thermische_leistung"),
        (CALC_COP, "es_hp_aktueller_cop"),
        (CALC_ELEC_POWER, "es_hp_leistung_elektrisch"),
    ):
        unique_id = f"{DOMAIN}_{username}_{calc_key}"
        current_id = ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id)
        if current_id is None:
            continue
        target_id = f"sensor.{target_slug}"
        if current_id == target_id:
            continue
        clash = ent_reg.async_get(target_id)
        if clash is not None and clash.unique_id != unique_id:
            continue
        _LOGGER.info("ES Heatpump: migrating %s → %s", current_id, target_id)
        ent_reg.async_update_entity(current_id, new_entity_id=target_id)

    # --- Step 2: remove orphaned parXX entities ---------------------------
    known_pars = set(PARAMETER_SENSORS.keys())
    removed = 0
    for ent in list(ent_reg.entities.values()):
        if ent.platform != DOMAIN:
            continue
        if ent.config_entry_id != entry.entry_id:
            continue
        m = _UNIQUE_ID_RE.match(ent.unique_id or "")
        if m is None:
            continue
        par_id = f"par{m.group(2)}"
        if par_id in known_pars:
            continue
        _LOGGER.info(
            "ES Heatpump: removing obsolete entity %s (par %s no longer exposed)",
            ent.entity_id, par_id,
        )
        ent_reg.async_remove(ent.entity_id)
        removed += 1

    if removed:
        _LOGGER.info("ES Heatpump: removed %d obsolete parameter entities", removed)
