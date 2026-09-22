"""Ablage der Konfigurationssicherungen in Home Assistant.

Gespeichert wird ueber ``homeassistant.helpers.storage.Store``, also in
``.storage/es_heatpump.backups_<entry_id>``. Damit liegen die Sicherungen dort,
wo auch alles andere von Home Assistant liegt: sie ueberleben Neustarts und
Updates, und sie landen in jedem HA-Backup - ohne dass dafuer irgendetwas
eingerichtet werden muesste.

Die eigentliche Logik (Vergleich, Aufraeumen, Planung) steht in ``backup.py``
und ist ohne Home Assistant testbar. Hier steht nur, was zwangslaeufig mit HA
zu tun hat.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable, Awaitable

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .backup import (
    ANLASS_AUTOMATISCH,
    ANLASS_ERSTE,
    ANLASS_MANUELL,
    ANLASS_VOR_WIEDERHERSTELLUNG,
    Sicherung,
    Wiederherstellungsplan,
    aufraeumen,
    aus_dict,
    neue_id,
    plane_wiederherstellung,
    pruefsumme_von,
    vergleiche,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = "es_heatpump.backups"


class Sicherungsablage:
    """Haelt die Sicherungen einer Anlage und schreibt sie fort."""

    def __init__(self, hass: HomeAssistant, entry_id: str, behalten: int) -> None:
        self._hass = hass
        self._behalten = behalten
        self._store: Store = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry_id}", private=True
        )
        self._sicherungen: list[Sicherung] = []
        self._geladen = False

    # ------------------------------------------------------------------
    # Laden / Speichern
    # ------------------------------------------------------------------

    async def async_laden(self) -> None:
        if self._geladen:
            return
        roh = await self._store.async_load()
        if isinstance(roh, dict):
            for eintrag in roh.get("sicherungen", []):
                try:
                    self._sicherungen.append(aus_dict(eintrag))
                except (TypeError, ValueError) as err:
                    _LOGGER.warning(
                        "ES Heatpump: Sicherung konnte nicht gelesen werden (%s) - "
                        "uebersprungen, die uebrigen bleiben nutzbar", err
                    )
        self._sicherungen.sort(key=lambda s: s.zeitpunkt, reverse=True)
        self._geladen = True
        _LOGGER.debug(
            "ES Heatpump: %d Konfigurationssicherungen geladen", len(self._sicherungen)
        )

    async def _async_speichern(self) -> None:
        await self._store.async_save(
            {
                "sicherungen": [
                    {
                        "id": s.id, "zeitpunkt": s.zeitpunkt, "anlass": s.anlass,
                        "label": s.label, "grund": s.grund, "pars": s.pars,
                        "stammdaten": s.stammdaten, "version": s.version,
                        "pruefsumme": s.pruefsumme,
                    }
                    for s in self._sicherungen
                ]
            }
        )

    # ------------------------------------------------------------------
    # Lesen
    # ------------------------------------------------------------------

    @property
    def alle(self) -> list[Sicherung]:
        return list(self._sicherungen)

    @property
    def neueste(self) -> Sicherung | None:
        return self._sicherungen[0] if self._sicherungen else None

    def hole(self, sicherung_id: str) -> Sicherung:
        """Sucht eine Sicherung; ``"neueste"`` und ``"aelteste"`` sind erlaubt."""
        if not self._sicherungen:
            raise LookupError("Es gibt noch keine Sicherung.")
        if sicherung_id in ("neueste", "latest", ""):
            return self._sicherungen[0]
        if sicherung_id in ("aelteste", "oldest"):
            return self._sicherungen[-1]
        for s in self._sicherungen:
            if s.id == sicherung_id:
                return s
        vorhanden = ", ".join(s.id for s in self._sicherungen[:5])
        raise LookupError(
            f"Keine Sicherung mit der Kennung {sicherung_id!r}. "
            f"Vorhanden sind z. B.: {vorhanden}"
        )

    # ------------------------------------------------------------------
    # Schreiben
    # ------------------------------------------------------------------

    async def async_erstelle(
        self,
        pars: dict[str, float],
        stammdaten: dict[str, Any],
        *,
        anlass: str = ANLASS_MANUELL,
        label: str = "",
        grund: str = "",
        version: str = "",
        nur_bei_aenderung: bool = False,
    ) -> Sicherung | None:
        """Legt eine Sicherung an.

        ``nur_bei_aenderung`` ist der Weg fuer den automatischen Takt: Wenn
        sich seit der letzten Sicherung nichts geaendert hat, entsteht keine
        neue. Sonst waere die Liste nach einer Woche voll mit identischen
        Staenden, und die eine Sicherung, die einen Eingriff dokumentiert,
        waere darin nicht mehr zu finden.
        """
        await self.async_laden()

        if not pars:
            raise ValueError("Leerer Konfigurationsstand - es wird nichts gesichert.")

        neu_summe = pruefsumme_von(pars)
        if nur_bei_aenderung and self.neueste and self.neueste.pruefsumme == neu_summe:
            _LOGGER.debug(
                "ES Heatpump: Konfiguration unveraendert (%s) - keine neue Sicherung",
                neu_summe,
            )
            return None

        if not self._sicherungen:
            anlass = ANLASS_ERSTE

        jetzt: datetime = dt_util.now()
        kennung = neue_id(jetzt)
        # Kollision bei zwei Sicherungen in derselben Sekunde
        laufend = 1
        while any(s.id == kennung for s in self._sicherungen):
            laufend += 1
            kennung = f"{neue_id(jetzt)}-{laufend}"

        sicherung = Sicherung(
            id=kennung,
            zeitpunkt=jetzt.isoformat(),
            anlass=anlass,
            label=label,
            grund=grund,
            pars=dict(pars),
            stammdaten=dict(stammdaten),
            version=version,
            pruefsumme=neu_summe,
        )
        self._sicherungen.insert(0, sicherung)

        bleiben, weg = aufraeumen(self._sicherungen, self._behalten)
        if weg:
            _LOGGER.info(
                "ES Heatpump: %d alte Sicherungen entfernt (Aufbewahrung: %d)",
                len(weg), self._behalten,
            )
            self._sicherungen = bleiben

        await self._async_speichern()
        _LOGGER.info(
            "ES Heatpump: Konfiguration gesichert - %s (%s, %d Werte, Prüfsumme %s)",
            kennung, anlass, len(pars), neu_summe,
        )
        return sicherung

    async def async_loesche(self, sicherung_id: str) -> Sicherung:
        await self.async_laden()
        s = self.hole(sicherung_id)
        self._sicherungen = [x for x in self._sicherungen if x.id != s.id]
        await self._async_speichern()
        _LOGGER.info("ES Heatpump: Sicherung %s geloescht", s.id)
        return s

    async def async_setze_aufbewahrung(self, behalten: int) -> None:
        self._behalten = behalten
        await self.async_laden()
        bleiben, weg = aufraeumen(self._sicherungen, behalten)
        if weg:
            self._sicherungen = bleiben
            await self._async_speichern()

    # ------------------------------------------------------------------
    # Wiederherstellen
    # ------------------------------------------------------------------

    async def async_wiederherstellen(
        self,
        sicherung_id: str,
        jetzt_pars: dict[str, Any],
        schreiber: Callable[[str, int], Awaitable[None]],
        stammdaten: dict[str, Any],
        *,
        probelauf: bool = True,
        version: str = "",
    ) -> dict[str, Any]:
        """Stellt einen gesicherten Stand wieder her.

        Ablauf, bewusst in dieser Reihenfolge:

        1. Plan bauen - was waere zu schreiben, was geht nicht.
        2. Bei ``probelauf`` hier aufhoeren und den Plan zurueckgeben.
        3. **Vor** dem ersten Schreibvorgang den jetzigen Stand sichern. Wer
           versehentlich den falschen Stand wiederherstellt, braucht genau
           diesen.
        4. Werte einzeln schreiben. Das Portal kennt keinen Sammelauftrag;
           jeder Wert geht einzeln. Ein Fehler bricht ab, statt die Anlage in
           einem halb gesetzten Zustand zu lassen - aber das bereits
           Geschriebene bleibt, und der Bericht sagt genau, wie weit es kam.
        """
        await self.async_laden()
        ziel = self.hole(sicherung_id)
        plan: Wiederherstellungsplan = plane_wiederherstellung(jetzt_pars, ziel.pars)

        bericht: dict[str, Any] = {
            "sicherung": ziel.kurzfassung(),
            "probelauf": probelauf,
            **plan.als_dict(),
        }

        if probelauf:
            bericht["ergebnis"] = (
                f"Probelauf - es wurde nichts geschrieben. "
                f"{plan.anzahl} Werte wuerden gesetzt."
            )
            return bericht

        if not plan.zu_schreiben:
            bericht["ergebnis"] = "Die Anlage steht bereits auf diesem Stand."
            return bericht

        vorher = await self.async_erstelle(
            jetzt_pars, stammdaten,
            anlass=ANLASS_VOR_WIEDERHERSTELLUNG,
            label=f"vor Wiederherstellung von {ziel.id}",
            grund=f"Automatisch angelegt, bevor {plan.anzahl} Werte gesetzt wurden.",
            version=version,
        )
        bericht["sicherung_vorher"] = vorher.kurzfassung() if vorher else None

        geschrieben: list[str] = []
        for a in plan.zu_schreiben:
            try:
                await schreiber(a.par, int(a.nachher))
            except Exception as err:  # noqa: BLE001
                bericht["ergebnis"] = (
                    f"Abgebrochen bei {a.par} ({a.name}): {err}. "
                    f"{len(geschrieben)} von {plan.anzahl} Werten waren da bereits "
                    f"gesetzt. Der Stand davor liegt als Sicherung "
                    f"{vorher.id if vorher else '?'} bereit."
                )
                bericht["geschrieben"] = geschrieben
                bericht["fehler"] = str(err)
                return bericht
            geschrieben.append(a.par)

        bericht["geschrieben"] = geschrieben
        bericht["ergebnis"] = (
            f"{len(geschrieben)} Werte gesetzt. Der Stand davor liegt als Sicherung "
            f"{vorher.id if vorher else '?'} bereit."
        )
        return bericht

    # ------------------------------------------------------------------
    # Vergleich
    # ------------------------------------------------------------------

    def vergleiche_zwei(self, a_id: str, b_id: str) -> dict[str, Any]:
        a, b = self.hole(a_id), self.hole(b_id)
        abweichungen = vergleiche(a.pars, b.pars)
        return {
            "von": a.kurzfassung(),
            "nach": b.kurzfassung(),
            "anzahl_abweichungen": len(abweichungen),
            "abweichungen": [x.als_dict() for x in abweichungen],
        }

    def vergleiche_mit_jetzt(self, a_id: str, jetzt: dict[str, Any]) -> dict[str, Any]:
        a = self.hole(a_id)
        abweichungen = vergleiche(a.pars, jetzt)
        return {
            "von": a.kurzfassung(),
            "nach": "aktueller Stand der Anlage",
            "anzahl_abweichungen": len(abweichungen),
            "abweichungen": [x.als_dict() for x in abweichungen],
        }
