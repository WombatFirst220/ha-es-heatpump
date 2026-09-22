"""Eigener Abruftakt fuer die Konfiguration - und der automatische Sicherungslauf.

Warum getrennt vom Messwert-Koordinator: Messwerte aendern sich im
Sekundentakt, Einstellungen im Monatstakt. Die Konfiguration alle 60 Sekunden
abzurufen wuerde das Portal 1440-mal am Tag fuer nichts belasten und die
Sitzung unnoetig strapazieren. Voreinstellung ist deshalb ein Abruf alle 15
Minuten - schnell genug, dass eine Aenderung an der Bedieneinheit binnen einer
Viertelstunde in Home Assistant sichtbar wird.

Der Koordinator ist zugleich die Stelle, an der der automatische Sicherungslauf
haengt: Nach jedem erfolgreichen Abruf wird geprueft, ob sich etwas geaendert
hat, und nur dann eine neue Sicherung angelegt. Damit dokumentiert die
Sicherungsliste **Aenderungen**, nicht den Kalender - auch eine, die jemand an
der Bedieneinheit im Heizungskeller vorgenommen hat.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .backup import ANLASS_AUTOMATISCH, ANLASS_VOR_SCHREIBEN, vergleiche
from .backup_store import Sicherungsablage
from .const import DOMAIN
from .coordinator import ESHeatpumpCoordinator

_LOGGER = logging.getLogger(__name__)


class ESHeatpumpSettingsCoordinator(DataUpdateCoordinator[dict[str, float]]):
    """Haelt den Konfigurationsstand aktuell und sichert ihn bei Aenderung."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: ESHeatpumpCoordinator,
        ablage: Sicherungsablage,
        scan_interval: int,
        backup_interval_h: int,
        version: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_settings",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.api = api
        self.ablage = ablage
        self._backup_interval = timedelta(hours=max(1, backup_interval_h))
        self._version = version
        # Nur zur Anzeige im Diagnosesensor - die Durchsetzung sitzt in den
        # Entities und den Diensten, nicht hier.
        self.schreiben_erlaubt = False

    async def _async_update_data(self) -> dict[str, float]:
        try:
            werte = await self.api.async_lies_konfiguration()
        except UpdateFailed:
            raise
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Konfiguration nicht lesbar: {err}") from err

        # Stammdaten-Kopf einmalig nachladen (Installateur, Artikelnummer)
        await self.api.async_lies_stammdaten_kopf()

        await self._pruefe_sicherung(werte)
        return werte

    async def _pruefe_sicherung(self, werte: dict[str, float]) -> None:
        """Legt eine Sicherung an, wenn es etwas zu sichern gibt.

        Zwei Ausloeser, und beide sind gewollt:

        * **Aenderung** - unabhaengig davon, wann zuletzt gesichert wurde. Wer
          an der Bedieneinheit etwas verstellt, soll das binnen einer
          Viertelstunde in der Sicherungsliste wiederfinden.
        * **Zeitablauf** - auch ohne Aenderung, damit die Liste nicht nach
          Monaten Stillstand mit einem einzigen Eintrag dasteht und man am
          Datum ablesen kann, dass wirklich nichts passiert ist.
        """
        await self.ablage.async_laden()
        neueste = self.ablage.neueste
        stammdaten = self.api.stammdaten.als_dict()

        if neueste is None:
            await self.ablage.async_erstelle(
                werte, stammdaten,
                grund="Erster gesicherter Stand nach Einrichtung der Integration.",
                version=self._version,
            )
            return

        from .backup import pruefsumme_von

        geaendert = pruefsumme_von(werte) != neueste.pruefsumme
        if geaendert:
            abweichungen = vergleiche(neueste.pars, werte)
            benannt = [a for a in abweichungen if a.bekannt]
            beschreibung = "; ".join(
                f"{a.name}: {a.vorher} → {a.nachher}" for a in benannt[:5]
            )
            if len(benannt) > 5:
                beschreibung += f" (und {len(benannt) - 5} weitere)"
            if not benannt:
                beschreibung = (
                    f"{len(abweichungen)} Werte ohne Katalogeintrag geaendert"
                )
            sicherung = await self.ablage.async_erstelle(
                werte, stammdaten,
                anlass=ANLASS_AUTOMATISCH,
                label="Änderung erkannt",
                grund=beschreibung,
                version=self._version,
            )
            if sicherung:
                _LOGGER.info(
                    "ES Heatpump: Konfigurationsänderung gesichert (%s): %s",
                    sicherung.id, beschreibung,
                )
            return

        # Nichts geaendert - nur nach Ablauf des Taktes eine Marke setzen
        try:
            letzte = dt_util.parse_datetime(neueste.zeitpunkt)
        except (TypeError, ValueError):
            letzte = None
        if letzte is None or (dt_util.now() - letzte) >= self._backup_interval:
            await self.ablage.async_erstelle(
                werte, stammdaten,
                anlass=ANLASS_AUTOMATISCH,
                label="Turnusmäßig",
                grund="Unverändert seit der letzten Sicherung.",
                version=self._version,
                nur_bei_aenderung=False,
            )

    # ------------------------------------------------------------------
    # Schreiben
    # ------------------------------------------------------------------

    async def async_setze(self, par: str, wert: int, *, sichern: bool = True) -> None:
        """Setzt einen Wert - mit Sicherung davor und Abgleich danach.

        Die Sicherung **vor** dem Schreiben ist der eigentliche Zweck der
        ganzen Uebung: Sie entsteht genau dann, wenn jemand etwas veraendert,
        und genau dieser Stand ist der, den man spaeter zurueckhaben will.
        """
        if sichern and self.data:
            await self.ablage.async_erstelle(
                dict(self.data),
                self.api.stammdaten.als_dict(),
                anlass=ANLASS_VOR_SCHREIBEN,
                label=f"vor Änderung von {par}",
                grund=f"Automatisch angelegt, bevor {par} auf {wert} gesetzt wurde.",
                version=self._version,
            )

        await self.api.async_schreibe_konfiguration(par, wert)

        # Optimistisch uebernehmen, damit die Oberflaeche sofort reagiert;
        # der naechste Abruf bestaetigt oder korrigiert.
        if self.data is not None:
            neu = dict(self.data)
            neu[par] = float(wert)
            self.async_set_updated_data(neu)

    async def async_setze_ohne_sicherung(self, par: str, wert: int) -> None:
        """Fuer die Wiederherstellung: dort wird EINMAL vorher gesichert."""
        await self.api.async_schreibe_konfiguration(par, wert)
