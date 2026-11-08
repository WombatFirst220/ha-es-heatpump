"""Logbuch-Beschreibung fuer das Ereignis ``es_heatpump_einstellung_geaendert`` (v4.1.0).

Ohne diese Datei zeigt das Logbuch fremde Ereignisse gar nicht an. Mit ihr
erscheint jede erkannte Einstellungsaenderung als Zeile "ES Heatpump -
Einstellung geaendert: Heizkurve: 38 °C → 40 °C" - auch dann, wenn jemand an
der Bedieneinheit im Keller etwas verstellt hat.

Der Text ist deutsch wie die Namen im Einstellungskatalog (``settings.py``);
das Logbuch kennt fuer Integrations-Ereignisse keine Uebersetzungen.
"""
from __future__ import annotations

from typing import Any, Callable

from homeassistant.core import Event, HomeAssistant, callback

from .backup import ereignis_text
from .const import DOMAIN, EVENT_EINSTELLUNG_GEAENDERT

try:
    from homeassistant.components.logbook import (
        LOGBOOK_ENTRY_MESSAGE,
        LOGBOOK_ENTRY_NAME,
    )
except ImportError:  # pragma: no cover - aeltere/abweichende Fassungen
    LOGBOOK_ENTRY_MESSAGE = "message"
    LOGBOOK_ENTRY_NAME = "name"


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, Any]]], None],
) -> None:
    """Meldet die Beschreibung des Ereignisses beim Logbuch an."""

    @callback
    def _beschreibe(event: Event) -> dict[str, Any]:
        aenderungen = event.data.get("aenderungen") or []
        text = ereignis_text(aenderungen) if isinstance(aenderungen, list) else ""
        return {
            LOGBOOK_ENTRY_NAME: "ES Heatpump",
            LOGBOOK_ENTRY_MESSAGE: f"Einstellung geändert: {text or '?'}",
        }

    async_describe_event(DOMAIN, EVENT_EINSTELLUNG_GEAENDERT, _beschreibe)
