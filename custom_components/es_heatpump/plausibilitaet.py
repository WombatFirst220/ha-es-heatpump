"""Reparaturhinweis bei unplausiblem COP (v4.1.0) - die reine Logik.

Ein COP unter 1 im Betrieb ist physikalisch unmoeglich: Die Waermepumpe gaebe
weniger Waerme ab, als sie Strom aufnimmt. Weil die thermische Leistung aus dem
EINGESTELLTEN Volumenstrom gerechnet wird, ist praktisch immer dieser zu
niedrig. Bis v4.0.1 stand das nur einmal im Log - wo es niemand liest. Seit
v4.1.0 erscheint zusaetzlich ein Reparaturhinweis unter Einstellungen ->
System -> Reparaturen.

Warum nicht beim ersten Ausreisser
----------------------------------
Einzelne Werte unter 1 sind normal und kein Einstellfehler:

* Anlauf des Verdichters: Strom fliesst sofort, die Spreizung baut sich erst
  ueber ein, zwei Portalabrufe auf.
* Abtauen und Umschalten Heizen/Warmwasser: Die Spreizung bricht kurz ein
  oder kehrt sich um.
* Zeitversatz: Die Strommessung (z.B. Shelly, sekundengenau) und die
  Portalwerte (minuetlich) gehoeren nicht zum selben Augenblick.

``COP_UNPLAUSIBEL_FOLGE`` = 5 aufeinanderfolgende Werte im Betrieb entsprechen
beim voreingestellten Abruftakt von 60 s rund fuenf Minuten. Das ist laenger
als jeder der genannten Uebergaenge (Anlauf ~2 min, Umschalten ~1-3 min), aber
kurz genug, dass ein falsch eingestellter Volumenstrom noch im ersten
Heizzyklus auffaellt. Werte ohne Betrieb (COP 0 oder nicht bestimmbar) zaehlen
weder mit noch unterbrechen sie die Folge - sie sagen ueber den Volumenstrom
nichts aus.

Der Hinweis verschwindet beim ersten Wert >= 1 wieder; ein richtig
eingestellter Volumenstrom liefert im eingeschwungenen Betrieb nie Werte
darunter.

Das Modul ist frei von Home-Assistant-Importen und laesst sich ohne HA testen.
"""
from __future__ import annotations

from .const import DOMAIN, NOMINAL_FLOW_RATES_M3H

# Anzahl aufeinanderfolgender Werte < 1 (im Betrieb), ab der gemeldet wird.
COP_UNPLAUSIBEL_FOLGE = 5

# translation_key des Reparaturhinweises (issues.cop_unplausibel)
ISSUE_COP_UNPLAUSIBEL = "cop_unplausibel"
# v4.1.1: eigener Text, wenn der unplausible COP beim Warmwasser auftritt. Die
# Umwaelzpumpe P0 versorgt beide Kreise - der Warmwasser-Volumenstrom ist dann
# meist zu niedrig eingestellt, nicht der des Heizkreises.
ISSUE_COP_UNPLAUSIBEL_WW = "cop_unplausibel_warmwasser"

# Betriebsart (intern, siehe mode.py), in der der Warmwasser-Volumenstrom gilt
_MODUS_WARMWASSER = "Brauchwasser"


def cop_issue_schluessel(modus: str | None) -> str:
    """translation_key des Hinweises passend zur Betriebsart."""
    return ISSUE_COP_UNPLAUSIBEL_WW if modus == _MODUS_WARMWASSER else ISSUE_COP_UNPLAUSIBEL

# README-Abschnitt "Den Volumenstrom richtig einstellen"
COP_LEARN_MORE_URL = (
    "https://github.com/WombatFirst220/ha-es-heatpump"
    "#-den-volumenstrom-richtig-einstellen"
)

AKTION_MELDEN = "melden"
AKTION_LOESCHEN = "loeschen"


def cop_issue_id(entry_id: str) -> str:
    """Kennung des Hinweises - je Eintrag, damit zwei Anlagen sich nicht stoeren."""
    return f"{ISSUE_COP_UNPLAUSIBEL}_{entry_id}"


def richtwert_text(modell: str | None) -> str:
    """Nominaler Volumenstrom laut Datenblatt - fuer das gewaehlte Modell oder alle.

    Sprachneutral (Modellbezeichnung + Zahl + Einheit), weil der Text als
    Platzhalter in alle Uebersetzungen eingesetzt wird.
    """
    if modell in NOMINAL_FLOW_RATES_M3H:
        return f"{modell}: {NOMINAL_FLOW_RATES_M3H[modell][1]:.2f} m³/h"
    return ", ".join(
        f"{m.split('-', 1)[0]} {werte[1]:.2f}"
        for m, werte in NOMINAL_FLOW_RATES_M3H.items()
    ) + " m³/h"


class CopWaechter:
    """Zaehlt aufeinanderfolgende unplausible COP-Werte und entscheidet ueber den Hinweis.

    ``messpunkt`` liefert ``AKTION_MELDEN`` (Hinweis anlegen),
    ``AKTION_LOESCHEN`` (Hinweis entfernen) oder ``None`` (nichts tun). Jede
    Aktion kommt nur einmal je Zustandswechsel, nicht bei jedem Abruf.
    """

    def __init__(self, folge: int = COP_UNPLAUSIBEL_FOLGE) -> None:
        self.folge = max(1, int(folge))
        self.serie = 0
        self.gemeldet = False
        self.letzter_cop: float | None = None

    def messpunkt(self, cop: float | None) -> str | None:
        # Kein Betrieb / nicht bestimmbar: weder zaehlen noch zuruecksetzen
        if cop is None or cop <= 0:
            return None
        if cop >= 1.0:
            self.serie = 0
            if self.gemeldet:
                self.gemeldet = False
                return AKTION_LOESCHEN
            return None
        self.serie += 1
        self.letzter_cop = cop
        if self.serie >= self.folge and not self.gemeldet:
            self.gemeldet = True
            return AKTION_MELDEN
        return None
