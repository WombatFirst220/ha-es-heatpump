"""
dashboard.py
────────────
Automatically creates the "ES Heatpump" Lovelace dashboard the first time
the integration is set up, and removes it when the integration is removed.

Strategy (version-safe across HA 2023.x–2025.x):
  1. Copy the bundled es_heatpump.yaml to <config>/dashboards/es_heatpump.yaml
  2. Register it as a YAML-file-based dashboard via the lovelace storage
     collection (hass.data["lovelace"]["dashboards_collection"]).
  3. If the lovelace collection is not yet available (rare edge case during
     very early startup), fall back to writing directly into the lovelace
     *storage* file and firing a persistent notification that asks the user
     to restart HA once.
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import storage as ha_storage

_LOGGER = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
DASHBOARD_URL_PATH = "es-heatpump"
DASHBOARD_TITLE = "ES Heatpump"
DASHBOARD_ICON = "mdi:heat-pump"

# Source YAML bundled inside the integration package
_YAML_SRC: Path = Path(__file__).parent / "dashboard" / "es_heatpump.yaml"
# Destination inside the HA config directory
_YAML_DEST_REL = "dashboards/es_heatpump.yaml"

# HA lovelace storage key (stable since HA 2022)
_LOVELACE_STORAGE_KEY = "lovelace_dashboards"
_LOVELACE_STORAGE_VERSION = 1


# ── Public API ───────────────────────────────────────────────────────────────

async def async_install_dashboard(hass: HomeAssistant) -> None:
    """
    Install the ES Heatpump dashboard.
    Called once from async_setup_entry on first install.
    Idempotent – does nothing if the dashboard already exists.
    """
    if await _dashboard_exists(hass):
        _LOGGER.debug("ES Heatpump: dashboard already exists, skipping install")
        return

    dest = Path(hass.config.config_dir) / _YAML_DEST_REL
    await _copy_yaml(hass, dest)

    registered = await _register_via_collection(hass)
    if not registered:
        registered = await _register_via_storage(hass)

    if registered:
        _LOGGER.info(
            "ES Heatpump: dashboard '%s' installed and visible in the sidebar.",
            DASHBOARD_TITLE,
        )
    else:
        _LOGGER.warning(
            "ES Heatpump: could not auto-register dashboard. "
            "Please add it manually from dashboards/%s", _YAML_DEST_REL
        )
        hass.components.persistent_notification.async_create(
            title="ES Heatpump – Dashboard",
            message=(
                "Das ES-Heatpump-Dashboard konnte nicht automatisch angelegt werden.\n\n"
                "Bitte manuell hinzufügen: **Einstellungen → Dashboards → Dashboard hinzufügen** "
                "und die Datei `dashboards/es_heatpump.yaml` aus dem HA-Konfig-Verzeichnis "
                "als YAML-Dashboard registrieren.\n\n"
                "*(The ES Heatpump dashboard could not be auto-installed. "
                "Please add it manually via Settings → Dashboards → Add dashboard.)*"
            ),
            notification_id="es_heatpump_dashboard_manual",
        )


async def async_remove_dashboard(hass: HomeAssistant) -> None:
    """
    Remove the ES Heatpump dashboard.
    Called from async_unload_entry so the sidebar stays clean.
    """
    removed = await _deregister_via_collection(hass)
    if not removed:
        await _deregister_via_storage(hass)

    dest = Path(hass.config.config_dir) / _YAML_DEST_REL
    if await hass.async_add_executor_job(dest.exists):
        await hass.async_add_executor_job(dest.unlink)
        _LOGGER.debug("ES Heatpump: removed dashboard YAML %s", dest)


# ── Internal helpers ─────────────────────────────────────────────────────────

async def _dashboard_exists(hass: HomeAssistant) -> bool:
    """Return True if a dashboard with our url_path already exists."""
    try:
        collection = _get_collection(hass)
        if collection is not None:
            return any(
                item.get("url_path") == DASHBOARD_URL_PATH
                for item in collection.async_items()
            )
    except Exception:  # noqa: BLE001
        pass

    # Fallback: check storage file
    store = _make_store(hass)
    data = await store.async_load()
    if data and isinstance(data.get("items"), list):
        return any(
            item.get("url_path") == DASHBOARD_URL_PATH
            for item in data["items"]
        )
    return False


async def _copy_yaml(hass: HomeAssistant, dest: Path) -> None:
    """Copy the bundled dashboard YAML to the HA config directory."""
    def _do_copy() -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_YAML_SRC, dest)

    await hass.async_add_executor_job(_do_copy)
    _LOGGER.debug("ES Heatpump: copied dashboard YAML to %s", dest)


def _get_collection(hass: HomeAssistant) -> Any | None:
    """Return the lovelace dashboards collection if available."""
    lovelace = hass.data.get("lovelace")
    if lovelace is None:
        return None
    # HA stores it under different keys depending on version
    for key in ("dashboards_collection", "dashboards"):
        coll = lovelace.get(key) if isinstance(lovelace, dict) else getattr(lovelace, key, None)
        if coll is not None:
            return coll
    return None


async def _register_via_collection(hass: HomeAssistant) -> bool:
    """Try to register the dashboard via the live lovelace collection."""
    collection = _get_collection(hass)
    if collection is None:
        return False
    try:
        await collection.async_create_item(
            {
                "url_path": DASHBOARD_URL_PATH,
                "title": DASHBOARD_TITLE,
                "icon": DASHBOARD_ICON,
                "show_in_sidebar": True,
                "require_admin": False,
                "mode": "yaml",
                "filename": _YAML_DEST_REL,
            }
        )
        return True
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("ES Heatpump: collection registration failed: %s", err)
        return False


def _make_store(hass: HomeAssistant) -> ha_storage.Store:
    return ha_storage.Store(hass, _LOVELACE_STORAGE_VERSION, _LOVELACE_STORAGE_KEY)


async def _register_via_storage(hass: HomeAssistant) -> bool:
    """
    Directly write the dashboard entry into the lovelace storage JSON file.
    Used as a fallback when the collection object is not yet available.
    HA will pick up the change on next restart.
    """
    try:
        store = _make_store(hass)
        data = await store.async_load() or {"items": []}
        items: list[dict] = data.setdefault("items", [])

        # Guard against duplicates
        if any(i.get("url_path") == DASHBOARD_URL_PATH for i in items):
            return True

        import uuid
        items.append(
            {
                "id": str(uuid.uuid4()),
                "url_path": DASHBOARD_URL_PATH,
                "title": DASHBOARD_TITLE,
                "icon": DASHBOARD_ICON,
                "show_in_sidebar": True,
                "require_admin": False,
                "mode": "yaml",
                "filename": _YAML_DEST_REL,
            }
        )
        await store.async_save(data)
        _LOGGER.info(
            "ES Heatpump: dashboard written to lovelace storage. "
            "A Home Assistant restart is needed for the dashboard to appear."
        )
        hass.components.persistent_notification.async_create(
            title="ES Heatpump – Neustart erforderlich",
            message=(
                "Das **ES Heatpump**-Dashboard wurde konfiguriert und erscheint "
                "nach einem **Neustart von Home Assistant** in der Seitenleiste.\n\n"
                "*(The ES Heatpump dashboard has been configured and will appear "
                "in the sidebar after a **Home Assistant restart**.)*"
            ),
            notification_id="es_heatpump_dashboard_restart",
        )
        return True
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("ES Heatpump: storage fallback failed: %s", err)
        return False


async def _deregister_via_collection(hass: HomeAssistant) -> bool:
    collection = _get_collection(hass)
    if collection is None:
        return False
    try:
        for item in collection.async_items():
            if item.get("url_path") == DASHBOARD_URL_PATH:
                await collection.async_delete_item(item["id"])
                return True
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("ES Heatpump: collection deregistration failed: %s", err)
    return False


async def _deregister_via_storage(hass: HomeAssistant) -> None:
    try:
        store = _make_store(hass)
        data = await store.async_load()
        if not data:
            return
        items = data.get("items", [])
        data["items"] = [i for i in items if i.get("url_path") != DASHBOARD_URL_PATH]
        await store.async_save(data)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("ES Heatpump: storage deregistration failed: %s", err)
