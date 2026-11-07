"""
hydraulic_card.py
─────────────────
Liefert die Heat Pump Hydraulic Card mit (v3.1.0).

Die Karte stammt von Sturmi77/heatpump-hydraulic-card und steht unter der
MIT-Lizenz (``www/heatpump-hydraulic-card.LICENSE``).  Sie wird unverändert
ausgeliefert, über einen eigenen statischen Pfad bereitgestellt und per
``frontend.add_extra_js_url`` geladen. Der Betreiber muss also nichts über
HACS bzw. den Marktplatz nachinstallieren.

Hat der Betreiber die Karte schon selbst als Lovelace-Ressource eingebunden,
lädt die Integration ihre Kopie **nicht**: Seine Version gewinnt, und die
Karte meldet keinen Konflikt zwischen zwei Kopien.
"""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CARD_VERSION = "0.18.0"
CARD_FILE: Path = Path(__file__).parent / "www" / "heatpump-hydraulic-card.js"
STATIC_BASE = f"/{DOMAIN}_static"
CARD_URL = f"{STATIC_BASE}/heatpump-hydraulic-card.js?v={CARD_VERSION}"

# Teile von Ressourcen-URLs, an denen eine selbst installierte Kopie erkannt wird.
# Bis 0.9.3 hieß das Repository heatpump-flow-card.
_FREMDE_KOPIE = ("heatpump-hydraulic-card", "heatpump-flow-card")

_DATA_KEY = f"{DOMAIN}_hydraulic_card"


async def async_register_card(hass: HomeAssistant) -> bool:
    """Stellt die Karte bereit. Gibt True zurück, wenn sie geladen werden kann.

    True heißt: entweder lädt die Integration ihre Kopie, oder der Betreiber hat
    eine eigene. In beiden Fällen kann das Dashboard die Karte verwenden.
    """
    status = hass.data.setdefault(_DATA_KEY, {"static": False, "url": False})

    if await _eigene_ressource_vorhanden(hass):
        _LOGGER.debug(
            "ES Heatpump: Hydraulik-Karte ist bereits als Lovelace-Ressource "
            "eingebunden, mitgelieferte Kopie wird nicht geladen."
        )
        return True

    if not CARD_FILE.exists():
        _LOGGER.warning("ES Heatpump: %s fehlt, Hydraulik-Karte nicht verfügbar.", CARD_FILE)
        return False

    # Ein statischer Pfad lässt sich je HA-Lauf nur einmal registrieren.
    if not status["static"]:
        await _registriere_statischen_pfad(hass)
        status["static"] = True

    if not status["url"]:
        from homeassistant.components.frontend import add_extra_js_url

        add_extra_js_url(hass, CARD_URL)
        status["url"] = True
        _LOGGER.debug("ES Heatpump: Hydraulik-Karte %s geladen", CARD_VERSION)
    return True


def async_unregister_card(hass: HomeAssistant) -> None:
    """Nimmt die Karte aus dem Frontend (der statische Pfad bleibt bis zum Neustart)."""
    status = hass.data.get(_DATA_KEY)
    if not status or not status["url"]:
        return
    try:
        from homeassistant.components.frontend import remove_extra_js_url

        remove_extra_js_url(hass, CARD_URL)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("ES Heatpump: remove_extra_js_url fehlgeschlagen (%s)", err)
    status["url"] = False


async def _registriere_statischen_pfad(hass: HomeAssistant) -> None:
    verzeichnis = str(CARD_FILE.parent)
    try:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_BASE, verzeichnis, True)]
        )
    except ImportError:
        # HA vor 2024.7
        hass.http.register_static_path(STATIC_BASE, verzeichnis, True)


async def _eigene_ressource_vorhanden(hass: HomeAssistant) -> bool:
    """Prüft die Lovelace-Ressourcen auf eine selbst installierte Kopie."""
    lovelace = hass.data.get("lovelace")
    if lovelace is None:
        return False
    resources = getattr(lovelace, "resources", None)
    if resources is None and isinstance(lovelace, dict):
        resources = lovelace.get("resources")
    if resources is None:
        return False
    try:
        # Die Storage-Sammlung lädt erst beim ersten Zugriff.
        if hasattr(resources, "async_get_info"):
            await resources.async_get_info()
        items = resources.async_items() or []
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("ES Heatpump: Lovelace-Ressourcen nicht lesbar (%s)", err)
        return False
    for item in items:
        url = str(item.get("url", ""))
        if url.startswith(STATIC_BASE):
            continue
        if any(teil in url for teil in _FREMDE_KOPIE):
            return True
    return False
