"""WebSocket-Befehle fuer die Auswertungsseite.

``es_heatpump/settings_changes`` liefert die Einstellungsaenderungen, die sich
aus den Konfigurationssicherungen ablesen lassen. Die Analysekarte
(``custom:es-heatpump-analysis-card``) markiert damit im Verlauf die Zeitpunkte,
zu denen sich an der Anlage etwas geaendert hat - Grundlage fuer den
Vergleich "vorher/nachher".

Anfrage::

    {"type": "es_heatpump/settings_changes", "entry_id": "<optional>"}

Antwort::

    {"changes": [{"time": "<ISO 8601, UTC>", "reason": "<anlass>",
                  "items": [{"par", "name", "group", "old", "new", "text"}]}]}

Die Ableitung selbst steht HA-frei in ``backup.aenderungsverlauf``.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .backup import aenderungsverlauf
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_DATA_KEY = f"{DOMAIN}_websocket"


@callback
def async_registriere_websocket(hass: HomeAssistant) -> None:
    """Registriert die Befehle einmal je HA-Lauf.

    Ein Befehl laesst sich nicht wieder abmelden; das Neuladen eines Eintrags
    darf ihn deshalb nicht ein zweites Mal anmelden.
    """
    if hass.data.get(_DATA_KEY):
        return
    websocket_api.async_register_command(hass, ws_settings_changes)
    hass.data[_DATA_KEY] = True


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/settings_changes",
        vol.Optional("entry_id"): str,
    }
)
@callback
def ws_settings_changes(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Einstellungsaenderungen einer Anlage, aelteste zuerst."""
    eintraege = {
        k: v for k, v in hass.data.get(DOMAIN, {}).items()
        if isinstance(v, dict) and v.get("ablage") is not None
    }
    gewuenscht = msg.get("entry_id")
    if gewuenscht:
        buendel = eintraege.get(gewuenscht)
        if buendel is None:
            connection.send_error(
                msg["id"], websocket_api.ERR_NOT_FOUND,
                f"Kein ES-Heatpump-Eintrag {gewuenscht!r}",
            )
            return
    elif eintraege:
        # Ohne Angabe: der erste Eintrag - im Normalfall gibt es genau einen.
        buendel = next(iter(eintraege.values()))
    else:
        # Noch keine Anlage geladen: leere Liste statt Fehler, die Karte zeigt
        # dann schlicht keine Markierungen.
        connection.send_result(msg["id"], {"changes": []})
        return

    try:
        aenderungen = aenderungsverlauf(buendel["ablage"].alle)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("ES Heatpump: Aenderungsverlauf nicht ableitbar: %s", err)
        connection.send_error(msg["id"], websocket_api.ERR_UNKNOWN_ERROR, str(err))
        return
    connection.send_result(msg["id"], {"changes": aenderungen})
