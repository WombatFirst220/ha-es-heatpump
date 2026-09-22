"""Dienste rund um die versionierte Konfigurationssicherung.

Alle lesenden Dienste liefern ihr Ergebnis als Dienstantwort zurueck
(``response_variable`` in einem Skript, oder der Knopf „Dienst ausfuehren“ in
den Entwicklerwerkzeugen zeigt sie direkt an). Damit laesst sich eine Sicherung
**einsehen**, ohne sie wiederherzustellen - was in der Praxis der haeufigere
Fall ist: Man will wissen, wie ein Wert vor drei Wochen stand, nicht sechzig
Werte zuruecksetzen.

Wiederherstellen ist bewusst unbequem gemacht:

* ``probelauf`` ist standardmaessig **an**. Der erste Aufruf zeigt also immer
  nur, was passieren wuerde.
* Ein echter Lauf verlangt zusaetzlich die Freigabe des Schreibzugriffs in den
  Optionen der Integration.
* Vor dem ersten Schreibvorgang entsteht automatisch eine Sicherung des
  jetzigen Standes.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .backup import ANLASS_MANUELL
from .const import (
    CONF_ENABLE_WRITES,
    DEFAULT_ENABLE_WRITES,
    DOMAIN,
    SERVICE_BACKUP_CREATE,
    SERVICE_BACKUP_DELETE,
    SERVICE_BACKUP_DIFF,
    SERVICE_BACKUP_EXPORT,
    SERVICE_BACKUP_LIST,
    SERVICE_BACKUP_RESTORE,
    SERVICE_BACKUP_SHOW,
    SERVICE_SET_PARAMETER,
)
from .settings import SETTINGS

_LOGGER = logging.getLogger(__name__)

ATTR_ENTRY = "eintrag"
ATTR_ID = "sicherung"
ATTR_ID2 = "vergleich_mit"
ATTR_LABEL = "bezeichnung"
ATTR_REASON = "grund"
ATTR_DRYRUN = "probelauf"
ATTR_PATH = "pfad"
ATTR_PAR = "parameter"
ATTR_VALUE = "wert"

_ID = vol.Any(cv.string, None)

SCHEMA_CREATE = vol.Schema({
    vol.Optional(ATTR_ENTRY): cv.string,
    vol.Optional(ATTR_LABEL, default=""): cv.string,
    vol.Optional(ATTR_REASON, default=""): cv.string,
})
SCHEMA_ID = vol.Schema({
    vol.Optional(ATTR_ENTRY): cv.string,
    vol.Required(ATTR_ID): cv.string,
})
SCHEMA_LIST = vol.Schema({vol.Optional(ATTR_ENTRY): cv.string})
SCHEMA_DIFF = vol.Schema({
    vol.Optional(ATTR_ENTRY): cv.string,
    vol.Required(ATTR_ID): cv.string,
    vol.Optional(ATTR_ID2, default="jetzt"): cv.string,
})
SCHEMA_RESTORE = vol.Schema({
    vol.Optional(ATTR_ENTRY): cv.string,
    vol.Required(ATTR_ID): cv.string,
    vol.Optional(ATTR_DRYRUN, default=True): cv.boolean,
})
SCHEMA_EXPORT = vol.Schema({
    vol.Optional(ATTR_ENTRY): cv.string,
    vol.Required(ATTR_ID): cv.string,
    vol.Optional(ATTR_PATH): cv.string,
})
SCHEMA_SET = vol.Schema({
    vol.Optional(ATTR_ENTRY): cv.string,
    vol.Required(ATTR_PAR): cv.string,
    vol.Required(ATTR_VALUE): vol.Coerce(float),
})


def _hole_daten(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    """Findet die gemeinte Anlage.

    Bei genau einer eingerichteten Anlage - dem Normalfall - braucht niemand
    eine Kennung anzugeben.
    """
    alle = hass.data.get(DOMAIN, {})
    eintraege = {k: v for k, v in alle.items() if isinstance(v, dict) and "settings" in v}
    if not eintraege:
        raise HomeAssistantError(
            "Keine ES-Heatpump-Anlage mit Konfigurationszugriff eingerichtet."
        )
    gewuenscht = call.data.get(ATTR_ENTRY)
    if gewuenscht:
        if gewuenscht not in eintraege:
            raise HomeAssistantError(
                f"Kein Eintrag {gewuenscht!r}. Vorhanden: {', '.join(eintraege)}"
            )
        return eintraege[gewuenscht]
    if len(eintraege) > 1:
        raise HomeAssistantError(
            "Es sind mehrere Anlagen eingerichtet - bitte 'eintrag' angeben: "
            + ", ".join(eintraege)
        )
    return next(iter(eintraege.values()))


def _schreiben_erlaubt(entry: ConfigEntry) -> bool:
    return bool(
        entry.options.get(
            CONF_ENABLE_WRITES,
            entry.data.get(CONF_ENABLE_WRITES, DEFAULT_ENABLE_WRITES),
        )
    )


async def async_registriere_dienste(hass: HomeAssistant) -> None:
    """Meldet alle Dienste an - einmal je Home-Assistant-Start."""

    if hass.services.has_service(DOMAIN, SERVICE_BACKUP_LIST):
        return

    # ── Sichern ───────────────────────────────────────────────────────
    async def sicherung_erstellen(call: ServiceCall) -> ServiceResponse:
        daten = _hole_daten(hass, call)
        koord = daten["settings"]
        if not koord.data:
            raise HomeAssistantError(
                "Der Konfigurationsstand ist gerade nicht bekannt. "
                "Nach dem nächsten erfolgreichen Abruf erneut versuchen."
            )
        sicherung = await koord.ablage.async_erstelle(
            dict(koord.data),
            koord.api.stammdaten.als_dict(),
            anlass=ANLASS_MANUELL,
            label=call.data.get(ATTR_LABEL, ""),
            grund=call.data.get(ATTR_REASON, ""),
            version=daten.get("version", ""),
        )
        return {"sicherung": sicherung.kurzfassung() if sicherung else None}

    # ── Auflisten ─────────────────────────────────────────────────────
    async def sicherungen_auflisten(call: ServiceCall) -> ServiceResponse:
        daten = _hole_daten(hass, call)
        ablage = daten["settings"].ablage
        await ablage.async_laden()
        return {
            "anzahl": len(ablage.alle),
            "sicherungen": [s.kurzfassung() for s in ablage.alle],
        }

    # ── Anzeigen ──────────────────────────────────────────────────────
    async def sicherung_anzeigen(call: ServiceCall) -> ServiceResponse:
        daten = _hole_daten(hass, call)
        ablage = daten["settings"].ablage
        await ablage.async_laden()
        try:
            s = ablage.hole(call.data[ATTR_ID])
        except LookupError as err:
            raise HomeAssistantError(str(err)) from err
        return {
            **s.kurzfassung(),
            "stammdaten": s.stammdaten,
            "einstellungen": s.lesbar(),
            "rohwerte": s.pars,
        }

    # ── Vergleichen ───────────────────────────────────────────────────
    async def sicherungen_vergleichen(call: ServiceCall) -> ServiceResponse:
        daten = _hole_daten(hass, call)
        koord = daten["settings"]
        await koord.ablage.async_laden()
        a = call.data[ATTR_ID]
        b = call.data.get(ATTR_ID2, "jetzt")
        try:
            if b in ("jetzt", "aktuell", "now"):
                if not koord.data:
                    raise HomeAssistantError(
                        "Der aktuelle Stand ist nicht bekannt - bitte zwei "
                        "Sicherungen vergleichen."
                    )
                return koord.ablage.vergleiche_mit_jetzt(a, dict(koord.data))
            return koord.ablage.vergleiche_zwei(a, b)
        except LookupError as err:
            raise HomeAssistantError(str(err)) from err

    # ── Wiederherstellen ──────────────────────────────────────────────
    async def sicherung_wiederherstellen(call: ServiceCall) -> ServiceResponse:
        daten = _hole_daten(hass, call)
        koord = daten["settings"]
        entry: ConfigEntry = daten["entry"]
        probelauf = bool(call.data.get(ATTR_DRYRUN, True))

        if not probelauf and not _schreiben_erlaubt(entry):
            raise HomeAssistantError(
                "Der Schreibzugriff ist abgeschaltet - es wurde nichts verändert. "
                "Einschalten in den Einstellungen der Integration unter "
                "„Schreibzugriff auf die Anlage erlauben“."
            )
        if not koord.data:
            raise HomeAssistantError(
                "Der jetzige Konfigurationsstand ist nicht bekannt. Ohne ihn "
                "lässt sich weder ein Plan bauen noch vorher sichern."
            )
        try:
            bericht = await koord.ablage.async_wiederherstellen(
                call.data[ATTR_ID],
                dict(koord.data),
                koord.async_setze_ohne_sicherung,
                koord.api.stammdaten.als_dict(),
                probelauf=probelauf,
                version=daten.get("version", ""),
            )
        except LookupError as err:
            raise HomeAssistantError(str(err)) from err
        if not probelauf:
            await koord.async_request_refresh()
        return bericht

    # ── Löschen ───────────────────────────────────────────────────────
    async def sicherung_loeschen(call: ServiceCall) -> ServiceResponse:
        daten = _hole_daten(hass, call)
        try:
            s = await daten["settings"].ablage.async_loesche(call.data[ATTR_ID])
        except LookupError as err:
            raise HomeAssistantError(str(err)) from err
        return {"geloescht": s.kurzfassung()}

    # ── Exportieren ───────────────────────────────────────────────────
    async def sicherung_exportieren(call: ServiceCall) -> ServiceResponse:
        daten = _hole_daten(hass, call)
        ablage = daten["settings"].ablage
        await ablage.async_laden()
        try:
            s = ablage.hole(call.data[ATTR_ID])
        except LookupError as err:
            raise HomeAssistantError(str(err)) from err

        pfad = call.data.get(ATTR_PATH) or hass.config.path(
            f"es_heatpump_konfiguration_{s.id}.json"
        )
        ziel = Path(pfad)
        if not hass.config.is_allowed_path(str(ziel.parent)):
            raise HomeAssistantError(
                f"{ziel.parent} steht nicht in 'allowlist_external_dirs' - "
                "Home Assistant darf dorthin nicht schreiben."
            )

        def _schreiben() -> None:
            ziel.parent.mkdir(parents=True, exist_ok=True)
            ziel.write_text(s.als_json(), encoding="utf-8")

        await hass.async_add_executor_job(_schreiben)
        _LOGGER.info("ES Heatpump: Sicherung %s exportiert nach %s", s.id, ziel)
        return {"datei": str(ziel), "sicherung": s.kurzfassung()}

    # ── Einzelnen Parameter setzen ────────────────────────────────────
    async def parameter_setzen(call: ServiceCall) -> ServiceResponse:
        daten = _hole_daten(hass, call)
        koord = daten["settings"]
        entry: ConfigEntry = daten["entry"]
        if not _schreiben_erlaubt(entry):
            raise HomeAssistantError(
                "Der Schreibzugriff ist abgeschaltet - es wurde nichts verändert."
            )
        par = str(call.data[ATTR_PAR]).strip()
        eintrag = SETTINGS.get(par)
        if eintrag is None:
            raise HomeAssistantError(
                f"{par} steht nicht im Katalog. Bekannt sind "
                f"{len(SETTINGS)} Felder, z. B. par1, par4, par55."
            )
        try:
            wert = eintrag.validate(call.data[ATTR_VALUE])
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        await koord.async_setze(par, wert)
        return {"parameter": par, "name": eintrag.name, "wert": wert}

    dienste = (
        (SERVICE_BACKUP_CREATE, sicherung_erstellen, SCHEMA_CREATE, SupportsResponse.OPTIONAL),
        (SERVICE_BACKUP_LIST, sicherungen_auflisten, SCHEMA_LIST, SupportsResponse.ONLY),
        (SERVICE_BACKUP_SHOW, sicherung_anzeigen, SCHEMA_ID, SupportsResponse.ONLY),
        (SERVICE_BACKUP_DIFF, sicherungen_vergleichen, SCHEMA_DIFF, SupportsResponse.ONLY),
        (SERVICE_BACKUP_RESTORE, sicherung_wiederherstellen, SCHEMA_RESTORE, SupportsResponse.OPTIONAL),
        (SERVICE_BACKUP_DELETE, sicherung_loeschen, SCHEMA_ID, SupportsResponse.OPTIONAL),
        (SERVICE_BACKUP_EXPORT, sicherung_exportieren, SCHEMA_EXPORT, SupportsResponse.OPTIONAL),
        (SERVICE_SET_PARAMETER, parameter_setzen, SCHEMA_SET, SupportsResponse.OPTIONAL),
    )
    for name, handler, schema, antwort in dienste:
        hass.services.async_register(
            DOMAIN, name, handler, schema=schema, supports_response=antwort
        )
    _LOGGER.debug("ES Heatpump: %d Dienste angemeldet", len(dienste))


def async_entferne_dienste(hass: HomeAssistant) -> None:
    for name in (
        SERVICE_BACKUP_CREATE, SERVICE_BACKUP_LIST, SERVICE_BACKUP_SHOW,
        SERVICE_BACKUP_DIFF, SERVICE_BACKUP_RESTORE, SERVICE_BACKUP_DELETE,
        SERVICE_BACKUP_EXPORT, SERVICE_SET_PARAMETER,
    ):
        hass.services.async_remove(DOMAIN, name)
