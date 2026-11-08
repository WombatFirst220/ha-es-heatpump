"""
analysis_card.py
────────────────
Liefert die Auswertungskarte ``custom:es-heatpump-analysis-card`` mit (v4.0.0).

Die Karte (``www/es-heatpump-analysis-card.js``) ist Teil der Integration,
kommt ohne Build-Schritt und ohne Fremdbibliotheken aus und liest die
Langzeitstatistik von Home Assistant (``recorder/statistics_during_period``)
sowie die Einstellungsaenderungen (``es_heatpump/settings_changes``).

Ausgeliefert wird sie ueber denselben statischen Pfad wie die Hydraulik-Karte
(``/es_heatpump_static``, ganz ``www/``); der Pfad wird je HA-Lauf nur einmal
registriert (``hydraulic_card.async_ensure_static_path``).  Geladen wird sie
per ``frontend.add_extra_js_url`` mit der Integrationsversion als
Cache-Brecher.
"""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .hydraulic_card import STATIC_BASE, async_ensure_static_path

_LOGGER = logging.getLogger(__name__)

ANALYSIS_CARD_TYPE = "custom:es-heatpump-analysis-card"
ANALYSIS_CARD_FILE: Path = Path(__file__).parent / "www" / "es-heatpump-analysis-card.js"
_DATA_KEY = f"{DOMAIN}_analysis_card"


async def _version(hass: HomeAssistant) -> str:
    try:
        from homeassistant.loader import async_get_integration

        integration = await async_get_integration(hass, DOMAIN)
        return str(integration.version or "0")
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("ES Heatpump: Version nicht ermittelbar (%s)", err)
        return "0"


async def async_register_analysis_card(hass: HomeAssistant) -> bool:
    """Stellt die Auswertungskarte bereit. Gibt True zurueck, wenn sie geladen wird."""
    status = hass.data.setdefault(_DATA_KEY, {"url": None})
    if status["url"]:
        return True

    vorhanden = await hass.async_add_executor_job(ANALYSIS_CARD_FILE.exists)
    if not vorhanden:
        _LOGGER.warning(
            "ES Heatpump: %s fehlt, Auswertungskarte nicht verfuegbar.", ANALYSIS_CARD_FILE
        )
        return False

    await async_ensure_static_path(hass)

    from homeassistant.components.frontend import add_extra_js_url

    url = f"{STATIC_BASE}/{ANALYSIS_CARD_FILE.name}?v={await _version(hass)}"
    add_extra_js_url(hass, url)
    status["url"] = url
    _LOGGER.debug("ES Heatpump: Auswertungskarte geladen (%s)", url)
    return True


def async_unregister_analysis_card(hass: HomeAssistant) -> None:
    """Nimmt die Karte aus dem Frontend (der statische Pfad bleibt bis zum Neustart)."""
    status = hass.data.get(_DATA_KEY)
    if not status or not status["url"]:
        return
    try:
        from homeassistant.components.frontend import remove_extra_js_url

        remove_extra_js_url(hass, status["url"])
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("ES Heatpump: remove_extra_js_url fehlgeschlagen (%s)", err)
    status["url"] = None
