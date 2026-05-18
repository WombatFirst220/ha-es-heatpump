"""
dashboard.py
────────────
Automatically installs / removes / updates the "ES Heatpump" Lovelace dashboard.

Strategy (proven reliable across HA 2023.x – 2025.x):
  1. Always copy the bundled YAML to <config>/dashboards/es_heatpump.yaml.
     The file is overwritten on every setup so plugin updates push the new
     layout without the user having to delete it manually.
  2. If the dashboard entry is not yet registered, add it directly to the
     .storage/lovelace_dashboards JSON file (HA's own storage format).
  3. Fire the lovelace_updated event so HA picks up the change immediately
     without requiring a full restart.
  4. If reload fails for any reason, show a persistent notification asking
     for a one-time restart.
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

# Bumping this string forces a re-copy of the bundled YAML (in case the user
# edited the file in-place — they'll see fresh content again on plugin update).
DASHBOARD_VERSION   = "2.0.0"

# YAML bundled inside the integration package
_YAML_SRC: Path = Path(__file__).parent / "dashboard" / "es_heatpump.yaml"
# Destination relative to <config>/
_YAML_DEST_REL  = "dashboards/es_heatpump.yaml"

# HA storage key for Lovelace dashboards (stable since HA 2021)
_STORE_KEY     = "lovelace_dashboards"
_STORE_VERSION = 1


# ── Public API ───────────────────────────────────────────────────────────────

async def async_install_dashboard(hass: HomeAssistant) -> None:
    """Install or update the ES Heatpump dashboard.

    Idempotent and safe to call on every HA startup. The bundled YAML is
    always re-copied so plugin updates take effect; the registry entry is
    only added once.
    """
    dest = Path(hass.config.config_dir) / _YAML_DEST_REL

    # ── Step 1: always copy the bundled YAML ─────────────────────────────
    try:
        await hass.async_add_executor_job(_copy_yaml, dest)
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("ES Heatpump: could not copy dashboard YAML: %s", err)
        return

    # ── Step 2: register dashboard entry if missing ──────────────────────
    store = ha_storage.Store(hass, _STORE_VERSION, _STORE_KEY)
    data = await store.async_load() or {"items": []}
    items: list[dict] = data.setdefault("items", [])

    already_registered = any(
        item.get("url_path") == DASHBOARD_URL_PATH for item in items
    )

    if already_registered:
        _LOGGER.debug(
            "ES Heatpump: dashboard already registered (YAML refreshed in place)"
        )
        # Still fire reload so an in-place YAML update becomes visible.
        await _async_reload_lovelace(hass)
        return

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
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("ES Heatpump: could not write to lovelace storage: %s", err)
        return

    # ── Step 3: tell HA to reload Lovelace without a restart ────────────
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
        try:
            hass.components.persistent_notification.async_create(
                title="ES Heatpump – Neustart erforderlich",
                message=(
                    "Das **ES Heatpump**-Dashboard wurde installiert und erscheint "
                    "nach einem **Neustart von Home Assistant** in der Seitenleiste."
                ),
                notification_id="es_heatpump_restart_required",
            )
        except Exception:  # noqa: BLE001
            pass


async def async_remove_dashboard(hass: HomeAssistant) -> None:
    """Remove the ES Heatpump dashboard entry and its YAML file."""
    store = ha_storage.Store(hass, _STORE_VERSION, _STORE_KEY)
    data = await store.async_load()
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
    except Exception:  # noqa: BLE001
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
    """Trigger a Lovelace reload so the sidebar updates without a restart.

    Tries multiple methods in order of reliability. Returns True if at least
    one method succeeded.
    """
    # Method A: call lovelace.reload_resources (HA 2022+)
    try:
        await hass.services.async_call(
            "lovelace", "reload_resources", blocking=True
        )
        _LOGGER.debug("ES Heatpump: lovelace.reload_resources called successfully")
        return True
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug(
            "ES Heatpump: reload_resources failed (%s), trying next method", err
        )

    # Method B: fire the lovelace_updated event directly
    try:
        hass.bus.async_fire(
            "lovelace_updated", {"url_path": None, "action": "create"}
        )
        _LOGGER.debug("ES Heatpump: lovelace_updated event fired")
        return True
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("ES Heatpump: lovelace_updated fire failed (%s)", err)

    # Method C: call frontend.reload_themes as a last-ditch refresh
    try:
        await hass.services.async_call(
            "frontend", "reload_themes", blocking=True
        )
        _LOGGER.debug("ES Heatpump: frontend.reload_themes called")
        return True
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("ES Heatpump: frontend reload failed (%s)", err)

    return False
