"""
dashboard.py
────────────
Automatically installs / updates / removes the "ES Heatpump" Lovelace dashboard.

v2.0.3+ writes the dashboard config in **storage mode**: the YAML bundled
inside the integration package is parsed once at setup time and stored
directly under ``.storage/lovelace.<id>``.  This avoids the issues of the
previous YAML-mode approach:

  * No dependency on a copied file in ``<config>/dashboards/`` — HACS or
    permission quirks can no longer leave us with stale content.
  * HA picks up the new layout on the next ``lovelace_updated`` event,
    no restart needed.
  * If a user had a legacy ``mode: yaml`` entry from an earlier plugin
    version, we transparently flip it to ``mode: storage`` and clean up
    the stranded YAML file.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

import yaml

from homeassistant.core import HomeAssistant
from homeassistant.helpers import storage as ha_storage

_LOGGER = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
DASHBOARD_URL_PATH = "es-heatpump"
DASHBOARD_TITLE    = "ES Heatpump"
DASHBOARD_ICON     = "mdi:heat-pump"

# YAML bundled inside the integration package
_YAML_SRC: Path = Path(__file__).parent / "dashboard" / "es_heatpump.yaml"

# HA storage keys
_INDEX_STORE_KEY = "lovelace_dashboards"
_INDEX_STORE_VER = 1
_DASH_STORE_VER  = 1

# Legacy file path (cleaned up if present)
_LEGACY_YAML_REL = "dashboards/es_heatpump.yaml"


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

async def async_install_dashboard(hass: HomeAssistant) -> None:
    """Install or update the ES Heatpump dashboard in storage mode.

    Idempotent — safe to call on every HA startup.  Re-parses the bundled
    YAML each time, so plugin updates are applied automatically.
    """
    # 1. Parse the bundled YAML
    config = await hass.async_add_executor_job(_load_bundled_yaml)
    if not config:
        _LOGGER.error(
            "ES Heatpump: bundled dashboard YAML at %s is missing or empty — "
            "skipping dashboard install.",
            _YAML_SRC,
        )
        return

    # 2. Locate or create the dashboard index entry
    index_store = ha_storage.Store(hass, _INDEX_STORE_VER, _INDEX_STORE_KEY)
    index_data = await index_store.async_load() or {"items": []}
    items: list[dict[str, Any]] = index_data.setdefault("items", [])

    existing = next(
        (i for i in items if i.get("url_path") == DASHBOARD_URL_PATH), None,
    )

    if existing is None:
        # Brand-new install
        dashboard_id = str(uuid.uuid4())
        items.append({
            "id":              dashboard_id,
            "url_path":        DASHBOARD_URL_PATH,
            "title":           DASHBOARD_TITLE,
            "icon":            DASHBOARD_ICON,
            "show_in_sidebar": True,
            "require_admin":   False,
            "mode":            "storage",
        })
        index_dirty = True
        _LOGGER.info("ES Heatpump: registering new dashboard %s", dashboard_id)
    else:
        dashboard_id = existing["id"]
        index_dirty = False
        # Convert legacy yaml-mode entries to storage-mode
        if existing.get("mode") != "storage":
            existing["mode"] = "storage"
            existing.pop("filename", None)
            index_dirty = True
            _LOGGER.info(
                "ES Heatpump: converting dashboard %s from yaml to storage mode",
                dashboard_id,
            )
        # Refresh title / icon in case they changed in code
        if existing.get("title") != DASHBOARD_TITLE:
            existing["title"] = DASHBOARD_TITLE
            index_dirty = True
        if existing.get("icon") != DASHBOARD_ICON:
            existing["icon"] = DASHBOARD_ICON
            index_dirty = True

    if index_dirty:
        await index_store.async_save(index_data)

    # 3. Write the actual dashboard config.
    #
    # HA's ``LovelaceStorage`` expects the stored data to be wrapped as
    # ``{"config": <user-config>}``.  In v2.1.0 we accidentally stored the
    # raw YAML at the top level, which led to a ``KeyError: 'config'`` in
    # ``components/lovelace/dashboard.py`` when the frontend tried to load
    # the view (resulting in an "Unknown error" toast).  Fixed in v2.1.1.
    config_store = ha_storage.Store(
        hass, _DASH_STORE_VER, f"lovelace.{dashboard_id}"
    )
    await config_store.async_save({"config": config})
    _LOGGER.debug(
        "ES Heatpump: wrote dashboard config to lovelace.%s (%d views)",
        dashboard_id, len(config.get("views", [])),
    )

    # 4. Trigger a reload so the UI updates immediately
    await _async_reload_lovelace(hass)

    # 5. Best-effort cleanup of the legacy YAML file
    legacy_path = Path(hass.config.config_dir) / _LEGACY_YAML_REL
    try:
        await hass.async_add_executor_job(_unlink_if_exists, legacy_path)
    except Exception:  # noqa: BLE001
        pass

    _LOGGER.info("ES Heatpump: dashboard '%s' ready", DASHBOARD_TITLE)


async def async_remove_dashboard(hass: HomeAssistant) -> None:
    """Remove the dashboard index entry and its stored config."""
    index_store = ha_storage.Store(hass, _INDEX_STORE_VER, _INDEX_STORE_KEY)
    index_data = await index_store.async_load()
    if not index_data:
        return

    removed_id: str | None = None
    items_kept: list[dict] = []
    for item in index_data.get("items", []):
        if item.get("url_path") == DASHBOARD_URL_PATH:
            removed_id = item["id"]
        else:
            items_kept.append(item)

    if removed_id:
        index_data["items"] = items_kept
        await index_store.async_save(index_data)

        # Drop the per-dashboard config storage file
        config_store = ha_storage.Store(
            hass, _DASH_STORE_VER, f"lovelace.{removed_id}"
        )
        try:
            await config_store.async_remove()
        except Exception:  # noqa: BLE001
            pass

    # Best-effort cleanup of any leftover legacy YAML
    legacy_path = Path(hass.config.config_dir) / _LEGACY_YAML_REL
    try:
        await hass.async_add_executor_job(_unlink_if_exists, legacy_path)
    except Exception:  # noqa: BLE001
        pass

    await _async_reload_lovelace(hass)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_bundled_yaml() -> dict[str, Any] | None:
    """Read & parse the bundled dashboard YAML synchronously (executor)."""
    if not _YAML_SRC.exists():
        return None
    try:
        with _YAML_SRC.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as err:
        _LOGGER.error("ES Heatpump: failed to parse bundled YAML: %s", err)
        return None
    return data if isinstance(data, dict) else None


def _unlink_if_exists(path: Path) -> None:
    if path.exists():
        path.unlink()
        _LOGGER.debug("ES Heatpump: removed legacy file %s", path)


async def _async_reload_lovelace(hass: HomeAssistant) -> bool:
    """Trigger a Lovelace reload without restarting HA.

    Tries multiple mechanisms in order of reliability. Returns True if any
    of them succeeded.
    """
    # Method A: fire the lovelace_updated event (most reliable for storage mode)
    try:
        hass.bus.async_fire(
            "lovelace_updated", {"url_path": DASHBOARD_URL_PATH, "action": "create"}
        )
        return True
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("ES Heatpump: lovelace_updated fire failed (%s)", err)

    # Method B: call lovelace.reload_resources (HA 2022+)
    try:
        await hass.services.async_call(
            "lovelace", "reload_resources", blocking=True
        )
        return True
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("ES Heatpump: reload_resources failed (%s)", err)

    return False
