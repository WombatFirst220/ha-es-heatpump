"""
dashboard.py
────────────
Automatically installs / removes the "ES Heatpump" Lovelace dashboard.

Strategy (proven reliable across HA 2023.x – 2025.x):
  1. Copy the bundled YAML to <config>/dashboards/es_heatpump.yaml
  2. Write the dashboard entry directly into the
     .storage/lovelace_dashboards JSON file (HA's own storage format).
  3. Fire the lovelace_updated event so HA picks up the change immediately
     WITHOUT needing a full restart.
  4. If firing the event fails for any reason, show a persistent notification
     asking for a one-time restart.
"""
from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import storage as ha_storage

_LOGGER = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
DASHBOARD_URL_PATH  = "es-heatpump"
DASHBOARD_TITLE     = "ES Heatpump"
DASHBOARD_ICON      = "mdi:heat-pump"

# YAML bundled inside the integration package
_YAML_SRC: Path = Path(__file__).parent / "dashboard" / "es_heatpump.yaml"
# Destination relative to <config>/
_YAML_DEST_REL      = "dashboards/es_heatpump.yaml"

# HA storage key for Lovelace dashboards (stable since HA 2021)
_STORE_KEY          = "lovelace_dashboards"
_STORE_VERSION      = 1


# ── Public API ───────────────────────────────────────────────────────────────

async def async_install_dashboard(hass: HomeAssistant) -> None:
    """
    Install the ES Heatpump dashboard.
    Idempotent – does nothing if the dashboard already exists.
    """
    store = ha_storage.Store(hass, _STORE_VERSION, _STORE_KEY)
    data  = await store.async_load() or {"items": []}
    items: list[dict] = data.setdefault("items", [])

    # ── Already installed? ────────────────────────────────────────────────
    if any(item.get("url_path") == DASHBOARD_URL_PATH for item in items):
        _LOGGER.debug("ES Heatpump: dashboard already registered, skipping")
        return

    # ── Step 1: copy YAML file ────────────────────────────────────────────
    dest = Path(hass.config.config_dir) / _YAML_DEST_REL
    try:
        await hass.async_add_executor_job(_copy_yaml, dest)
    except Exception as err:
        _LOGGER.error("ES Heatpump: could not copy dashboard YAML: %s", err)
        return

    # ── Step 2: add entry to storage ──────────────────────────────────────
    entry: dict[str, Any] = {
        "id":              str(uuid.uuid4()),
        "url_path":        DASHBOARD_URL_PATH,
        "title":           DASHBOARD_TITLE,
        "icon":            DASHBOARD_ICON,
        "show_in_sidebar": True,
        "require_admin":   False,
        "mode":            "yaml",
        "filename":        _YAML_DEST_REL,
    }
    items.append(entry)

    try:
        await store.async_save(data)
        _LOGGER.debug("ES Heatpump: dashboard entry written to lovelace storage")
    except Exception as err:
        _LOGGER.error("ES Heatpump: could not write to lovelace storage: %s", err)
        return

    # ── Step 3: tell HA to reload Lovelace without a restart ─────────────
    reloaded = await _async_reload_lovelace(hass)

    if reloaded:
        _LOGGER.info(
            "ES Heatpump: dashboard '%s' installed and visible in the sidebar.",
            DASHBOARD_TITLE,
        )
    else:
        _LOGGER.warning(
            "ES Heatpump: dashboard registered but Lovelace reload failed. "
            "A Home Assistant restart is needed for it to appear in the sidebar."
        )
        hass.components.persistent_notification.async_create(
            title="ES Heatpump – Neustart erforderlich / Restart required",
            message=(
                "Das **ES Heatpump**-Dashboard wurde installiert und erscheint nach "
                "einem **Neustart von Home Assistant** in der Seitenleiste.\n\n"
                "*(The ES Heatpump dashboard has been installed and will appear "
                "in the sidebar after a **Home Assistant restart**.)*"
            ),
            notification_id="es_heatpump_restart_required",
        )


async def async_remove_dashboard(hass: HomeAssistant) -> None:
    """
    Remove the ES Heatpump dashboard entry and its YAML file.
    Called when the last config entry is removed.
    """
    store = ha_storage.Store(hass, _STORE_VERSION, _STORE_KEY)
    data  = await store.async_load()
    if data:
        original_len = len(data.get("items", []))
        data["items"] = [
            i for i in data.get("items", [])
            if i.get("url_path") != DASHBOARD_URL_PATH
        ]
        if len(data["items"]) < original_len:
            await store.async_save(data)
            _LOGGER.debug("ES Heatpump: dashboard entry removed from lovelace storage")

    dest = Path(hass.config.config_dir) / _YAML_DEST_REL
    try:
        await hass.async_add_executor_job(_remove_yaml, dest)
    except Exception:
        pass

    await _async_reload_lovelace(hass)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _copy_yaml(dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_YAML_SRC, dest)
    _LOGGER.debug("ES Heatpump: copied dashboard YAML → %s", dest)


def _remove_yaml(dest: Path) -> None:
    if dest.exists():
        dest.unlink()
        _LOGGER.debug("ES Heatpump: removed dashboard YAML %s", dest)


async def _async_reload_lovelace(hass: HomeAssistant) -> bool:
    """
    Trigger a Lovelace reload so the sidebar updates without a restart.
    Tries multiple methods in order of reliability.
    Returns True if at least one method succeeded.
    """

    # Method A: call the lovelace.reload_resources service (HA 2022+)
    try:
        await hass.services.async_call(
            "lovelace", "reload_resources", blocking=True
        )
        _LOGGER.debug("ES Heatpump: lovelace.reload_resources called successfully")
        return True
    except Exception as err:
        _LOGGER.debug("ES Heatpump: reload_resources failed (%s), trying next method", err)

    # Method B: fire the lovelace_updated event directly
    try:
        hass.bus.async_fire("lovelace_updated", {"url_path": None, "action": "create"})
        _LOGGER.debug("ES Heatpump: lovelace_updated event fired")
        return True
    except Exception as err:
        _LOGGER.debug("ES Heatpump: lovelace_updated fire failed (%s)", err)

    # Method C: call the frontend.reload service
    try:
        await hass.services.async_call(
            "frontend", "reload_themes", blocking=True
        )
        _LOGGER.debug("ES Heatpump: frontend.reload_themes called")
        return True
    except Exception as err:
        _LOGGER.debug("ES Heatpump: frontend reload failed (%s)", err)

    return False
