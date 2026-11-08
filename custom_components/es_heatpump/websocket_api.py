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

``es_heatpump/analysis_config`` (v4.0.1) nennt der Karte die Entity-IDs, aus
denen sie ihre Werte holt - auch fuer die Zeit vor den eigenen Zaehlern::

    {"type": "es_heatpump/analysis_config", "entry_id": "<optional>"}

Antwort::

    {"electrical_power": "sensor.es_hp_leistung_elektrisch",
     "thermal_power": "sensor.es_hp_thermische_leistung",
     "energy_entity": "<Stromzaehler aus den Optionen oder null>",
     "power_entity": "<Strommess-Entity aus den Optionen oder null>",
     "counters": {"el": ..., "el_heat": ..., "el_dhw": ..., "el_standby": ...,
                  "th": ..., "th_heat": ..., "th_dhw": ..., "starts": ...,
                  "runtime": ...},
     "binary": {"verdichter": ..., "abtauen": ..., "warmwasser": ...,
                "takten": ...},
     "outdoor": ..., "cop": ..., "flow": ..., "carnot": ...}

``el_standby``, ``binary`` und ``carnot`` kamen mit v4.1.0 hinzu, ebenso
``frequency`` (Verdichterfrequenz par20) und ``mode`` (Betriebsart): Aus deren
Zustandsverlauf rekonstruiert die Karte einzelne Verdichterzyklen (Abschnitt
"Takten / Verdichterzyklen")::

     "frequency": "sensor.es_hp_frequenz_hz", "mode": "sensor.es_hp_betriebsart"

Die IDs kommen ueber die ``unique_id`` aus der Entity-Registry, damit eine
vom Nutzer umbenannte Entity gefunden wird; sonst gilt die Standard-ID.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .backup import aenderungsverlauf
from .const import CALC_BETRIEBSART, DOMAIN
from .energy import analyse_konfiguration

_LOGGER = logging.getLogger(__name__)

_DATA_KEY = f"{DOMAIN}_websocket"

# Verlaufsreihen fuer die Zyklen-Rekonstruktion der Karte (v4.1.0):
# Schluessel der Antwort -> (unique_id-Endung, Standard-Slug)
VERLAUF_REIHEN: dict[str, tuple[str, str]] = {
    "frequency": ("par20", "frequenz_hz"),
    "mode": (CALC_BETRIEBSART, "betriebsart"),
}


@callback
def async_registriere_websocket(hass: HomeAssistant) -> None:
    """Registriert die Befehle einmal je HA-Lauf.

    Ein Befehl laesst sich nicht wieder abmelden; das Neuladen eines Eintrags
    darf ihn deshalb nicht ein zweites Mal anmelden.
    """
    if hass.data.get(_DATA_KEY):
        return
    websocket_api.async_register_command(hass, ws_settings_changes)
    websocket_api.async_register_command(hass, ws_analysis_config)
    hass.data[_DATA_KEY] = True


def _buendel_waehlen(hass: HomeAssistant, entry_id: str | None) -> dict | None:
    """Daten eines geladenen Eintrags; ohne Angabe der erste."""
    eintraege = {
        k: v for k, v in hass.data.get(DOMAIN, {}).items()
        if isinstance(v, dict) and v.get("entry") is not None
    }
    if entry_id:
        return eintraege.get(entry_id)
    return next(iter(eintraege.values()), None)


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


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/analysis_config",
        vol.Optional("entry_id"): str,
    }
)
@callback
def ws_analysis_config(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Entity-IDs fuer die Auswertungskarte."""
    from homeassistant.const import CONF_USERNAME
    from homeassistant.helpers import entity_registry as er

    gewuenscht = msg.get("entry_id")
    buendel = _buendel_waehlen(hass, gewuenscht)
    if buendel is None and gewuenscht:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND,
            f"Kein ES-Heatpump-Eintrag {gewuenscht!r}",
        )
        return

    benutzer: str | None = None
    optionen: dict[str, Any] = {}
    if buendel is not None:
        entry = buendel["entry"]
        benutzer = entry.data.get(CONF_USERNAME)
        # Optionen vor Ersteinrichtung, wie in sensor.py
        optionen = {**entry.data, **entry.options}

    registry = er.async_get(hass)

    def finde(unique_id: str, plattform: str = "sensor") -> str | None:
        return registry.async_get_entity_id(plattform, DOMAIN, unique_id)

    antwort = analyse_konfiguration(finde, benutzer, optionen)
    for schluessel, (endung, slug) in VERLAUF_REIHEN.items():
        gefunden = finde(f"{DOMAIN}_{benutzer}_{endung}") if benutzer else None
        antwort[schluessel] = gefunden or f"sensor.es_hp_{slug}"
    connection.send_result(msg["id"], antwort)
