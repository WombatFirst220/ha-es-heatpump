"""Diagnosedaten eines Eintrags (v4.1.0) - "Diagnosedaten herunterladen".

Ziel: Bei einem Fehlerbericht soll eine einzige Datei reichen, um zu sehen,
was die Integration vom Portal bekommt und was sie daraus macht - ohne dass
jemand Logs zusammensuchen oder Zugangsdaten herausgeben muss.

Enthalten:
* Version der Integration, Optionen und Einrichtungsdaten (geschwaerzt)
* letzte Messwerte (``parXX``) und die Zusatzfelder der Portal-Antwort
  (``_raw_meta``)
* Konfigurationsstand: Anzahl und Werte
* Kurzfassung der Sicherungen (ohne Stammdaten, nur Zeitpunkt/Anlass/Grund)
* Zaehlerstaende der Energie-Bilanz
* aufgeloeste Betriebsart samt Begruendung
* Zustand beider Koordinatoren (letzter Abruf erfolgreich, letzte Ausnahme)

Was geschwaerzt wird und warum, steht in ``diagnose.py``.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant

from .backup import aussetzer
from .const import DOMAIN
from .diagnose import schwaerze_texte, zu_schwaerzende_schluessel
from .mode import resolve_betriebsart


def _koordinator(koord: Any) -> dict[str, Any] | None:
    """Zustand eines DataUpdateCoordinators, ohne seine Daten."""
    if koord is None:
        return None
    ausnahme = getattr(koord, "last_exception", None)
    intervall = getattr(koord, "update_interval", None)
    return {
        "last_update_success": getattr(koord, "last_update_success", None),
        "letzte_ausnahme": (
            f"{type(ausnahme).__name__}: {ausnahme}" if ausnahme is not None else None
        ),
        "update_interval_s": intervall.total_seconds() if intervall else None,
    }


def _energie_bilanz(bilanz: Any) -> dict[str, Any] | None:
    if bilanz is None:
        return None
    zaehler = getattr(bilanz, "zaehler", {}) or {}
    verdichter = getattr(bilanz, "verdichter", None)
    folger = getattr(bilanz, "folger", None)
    return {
        "elektrisch_quelle": getattr(bilanz, "elektrisch_quelle", None),
        "zaehler_kwh": {
            art: {teil: round(wert, 4) for teil, wert in z.summen.items()}
            for art, z in zaehler.items()
        },
        "verdichter": None if verdichter is None else {
            "starts": verdichter.starts,
            "laufzeit_h": round(verdichter.laufzeit_h, 4),
        },
        "stromzaehler_basis_kwh": None if folger is None else folger.basis,
    }


def _betriebsart(hass: HomeAssistant, entry: ConfigEntry, daten: dict[str, Any]) -> dict[str, Any]:
    # messoptionen liegt in sensor.py; erst hier importieren, damit die
    # Diagnose die Plattform nicht schon beim Laden der Integration zieht.
    from .sensor import messoptionen

    o = messoptionen(entry)
    try:
        modus, begruendung = resolve_betriebsart(
            hass, o["mode_source"], daten, o["dhw_margin_k"]
        )
    except Exception as err:  # noqa: BLE001 - Diagnose darf nicht scheitern
        return {"fehler": str(err)}
    return {
        "modus": modus,
        "begruendung": begruendung,
        "mode_source": o["mode_source"],
        "dhw_margin_k": o["dhw_margin_k"],
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Diagnosedaten eines Eintrags - geschwaerzt."""
    buendel = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    api = buendel.get("api")
    settings = buendel.get("settings")
    ablage = buendel.get("ablage")

    messdaten: dict[str, Any] = dict(getattr(api, "data", None) or {})
    raw_meta = messdaten.pop("_raw_meta", None)

    sicherungen: list[dict[str, Any]] = []
    aussetzer_ids: dict[str, str] = {}
    if ablage is not None:
        alle = list(ablage.alle)
        aussetzer_ids = aussetzer(alle)
        # Nur die Kurzfassung: Die Stammdaten in jeder Sicherung enthalten
        # Seriennummern, Besitzer und Installateur.
        sicherungen = [s.kurzfassung() for s in alle]

    einstellungen = dict(getattr(settings, "data", None) or {})
    stammdaten = api.stammdaten.als_dict() if api is not None else {}

    daten: dict[str, Any] = {
        "version": buendel.get("version"),
        "eintrag": {
            "title": entry.title,
            "version": entry.version,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "koordinator_messwerte": _koordinator(api),
        "koordinator_einstellungen": _koordinator(settings),
        "schreiben_erlaubt": getattr(settings, "schreiben_erlaubt", None),
        "messwerte": messdaten,
        "raw_meta": raw_meta,
        "einstellungen": {
            "anzahl": len(einstellungen),
            "werte": einstellungen,
        },
        "sicherungen": {
            "anzahl": len(sicherungen),
            "aussetzer": aussetzer_ids,
            "liste": sicherungen,
        },
        "stammdaten": stammdaten,
        "energie_bilanz": _energie_bilanz(buendel.get("bilanz")),
        "betriebsart": _betriebsart(hass, entry, getattr(api, "data", None) or {}),
    }

    geschwaerzt = async_redact_data(daten, zu_schwaerzende_schluessel(daten))
    # Benutzername und E-Mail-Adressen auch in Texten (Titel, Gruende)
    return schwaerze_texte(geschwaerzt, [entry.data.get(CONF_USERNAME)])
