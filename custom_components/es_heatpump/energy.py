"""Energiezaehler fuer die Auswertungsseite - die reine Logik.

Warum eigene Zaehler
--------------------
Die Waermepumpe liefert Leistungen (W), keine Arbeit (kWh). Fuer Tages-,
Wochen-, Monats- und Jahreswerte braucht die Langzeitstatistik von Home
Assistant aber Zaehler mit ``state_class: total_increasing``. Diese Zaehler
entstehen hier durch Integration ueber die Zeit:

* **elektrisch** - Leistung der konfigurierten Strommess-Entity (Shelly,
  Smart-Meter). Ihr Zustand gilt, bis er sich aendert; deshalb wird links
  integriert (Rechteck mit dem Wert zu Beginn des Intervalls).
* **thermisch** - die berechnete Waermeleistung (wie ``ThermLeistungSensor``)
  bei jedem Portalabruf, per Trapezregel.
* **Verdichter** - Starts (Wechsel der Frequenz par20 von 0 auf > 0) und
  Laufzeit (Zeit mit par20 > 0).

Aufteilung nach Betriebsart: Massgeblich ist die Betriebsart zu Beginn des
Intervalls. "Heizen" und "Entfrosten" zaehlen zum Heizen, die drei
Brauchwasser-Betriebsarten zum Warmwasser, alles Uebrige nur zur Summe.

Luecken: Liegen zwei Messpunkte weiter auseinander als ``max_luecke_s``
(HA-Neustart, Portal-Ausfall), wird das Intervall verworfen statt geschaetzt.
Ein Zaehler zaehlt lieber etwas zu wenig als eine erfundene Stunde.

Dieses Modul ist frei von Home-Assistant-Importen und laesst sich ohne HA
testen (``tests/test_energy.py``). Die Anbindung steht in ``sensor.py``.
"""
from __future__ import annotations

import math
from typing import Any

from .const import WATER_VOL_HEAT_CAPACITY_WH
from .flow import active_flow_rate

# Schluessel der Teilzaehler
GESAMT = "gesamt"
HEIZEN = "heizen"
WARMWASSER = "warmwasser"
TEILE = (GESAMT, HEIZEN, WARMWASSER)

# Maximale Luecke zwischen zwei Messpunkten, die noch integriert wird
MAX_LUECKE_ELEKTRISCH_S = 15 * 60
MAX_LUECKE_THERMISCH_S = 10 * 60
MAX_LUECKE_VERDICHTER_S = 10 * 60

# Art der Energie
ART_ELEKTRISCH = "elektrisch"
ART_THERMISCH = "thermisch"

# Zaehler-Entities: (slug = translation_key, Art, Teilzaehler). Die Entity-IDs
# lauten sensor.es_hp_<slug>; die Analysekarte verlaesst sich darauf.
ENERGIE_ZAEHLER = (
    ("energie_elektrisch", ART_ELEKTRISCH, GESAMT),
    ("energie_elektrisch_heizen", ART_ELEKTRISCH, HEIZEN),
    ("energie_elektrisch_warmwasser", ART_ELEKTRISCH, WARMWASSER),
    ("energie_thermisch", ART_THERMISCH, GESAMT),
    ("energie_thermisch_heizen", ART_THERMISCH, HEIZEN),
    ("energie_thermisch_warmwasser", ART_THERMISCH, WARMWASSER),
)

METHODE_LINKS = "links"
METHODE_TRAPEZ = "trapez"

# Betriebsart (deutsche interne Werte aus mode.py) -> Teilzaehler
_KATEGORIE = {
    "Heizen": HEIZEN,
    "Entfrosten": HEIZEN,
    "Brauchwasser": WARMWASSER,
    "Brauchwasser + Heizen": WARMWASSER,
    "Brauchwasser + Kuehlen": WARMWASSER,
}

# Einheiten der Strommess-Entity -> Faktor auf W
_LEISTUNG_IN_W = {"W": 1.0, "w": 1.0, "kW": 1000.0, "kw": 1000.0, "MW": 1e6}


def kategorie_von(betriebsart: str | None) -> str | None:
    """Teilzaehler fuer eine Betriebsart; ``None`` = nur Gesamtsumme."""
    if betriebsart is None:
        return None
    return _KATEGORIE.get(betriebsart)


def leistung_in_w(roh: Any, einheit: str | None = None) -> float | None:
    """Zustand einer Leistungs-Entity als Betrag in W.

    Betrag wie beim Spiegel-Sensor ``sensor.es_hp_leistung_elektrisch``: Viele
    Zaehler melden den Bezug negativ. ``unknown``/``unavailable`` und alles
    Nicht-Numerische ergeben ``None``. Eine Entity in kW wird umgerechnet -
    der Spiegel-Sensor tut das nicht, fuer einen Zaehler waere der Faktor
    1000 aber fatal.
    """
    if roh in (None, "", "unknown", "unavailable"):
        return None
    try:
        wert = abs(float(roh))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(wert):
        return None
    return wert * _LEISTUNG_IN_W.get(einheit or "W", 1.0)


def thermische_leistung_w(
    data: dict[str, Any] | None,
    betriebsart: str,
    flow_heating: float,
    flow_dhw: float,
    live_flow: float | None = None,
) -> float | None:
    """Waermeleistung in W, ungerundet.

    P = Volumenstrom [m3/h] x Spreizung [K] x 1163 Wh/(m3*K)

    ``None``, wenn Vor- oder Ruecklauf fehlen; 0, wenn der Verdichter steht,
    die Betriebsart keinen Waermeeintrag hat oder die Spreizung nicht positiv
    ist. Gemeinsame Grundlage fuer ``ThermLeistungSensor``, ``COPSensor`` und
    den thermischen Energiezaehler.
    """
    data = data or {}
    vor, rue, freq = data.get("par4"), data.get("par5"), data.get("par20")
    if vor is None or rue is None:
        return None
    if not freq or freq <= 0:
        return 0.0
    fluss = active_flow_rate(betriebsart, flow_heating, flow_dhw, live_flow)
    if fluss <= 0:
        return 0.0
    spreizung = vor - rue
    if spreizung <= 0:
        return 0.0
    return fluss * spreizung * WATER_VOL_HEAT_CAPACITY_WH


class EnergieZaehler:
    """Integriert eine Leistung (W) zu Energie (kWh), aufgeteilt nach Betriebsart.

    ``messpunkt`` wird mit jedem neuen Wert aufgerufen. Ein Wert ``None``
    (unbekannt/nicht verfuegbar) beendet die laufende Kette: Bei der linken
    Methode zaehlt das Intervall bis dahin noch mit dem alten Wert - der galt
    ja bis zu diesem Zeitpunkt -, bei der Trapezregel faellt es weg, weil der
    Endwert fehlt.
    """

    def __init__(self, max_luecke_s: float, methode: str = METHODE_LINKS) -> None:
        if methode not in (METHODE_LINKS, METHODE_TRAPEZ):
            raise ValueError(f"Unbekannte Methode {methode!r}")
        self.max_luecke_s = float(max_luecke_s)
        self.methode = methode
        self.summen: dict[str, float] = {t: 0.0 for t in TEILE}
        self._letzt: tuple[float, float, str | None] | None = None

    def uebernehme(self, teil: str, kwh: float) -> None:
        """Wiederhergestellten Zaehlerstand addieren (nach einem Neustart).

        Addiert statt zu setzen: Was zwischen Start und Wiederherstellung
        schon integriert wurde, geht so nicht verloren.
        """
        if teil not in self.summen:
            raise KeyError(teil)
        try:
            wert = float(kwh)
        except (TypeError, ValueError):
            return
        if wert > 0 and math.isfinite(wert):
            self.summen[teil] += wert

    def messpunkt(
        self, t: float, leistung_w: float | None, kategorie: str | None = None
    ) -> float:
        """Neuer Messpunkt zur Zeit ``t`` (Sekunden). Liefert die addierten kWh."""
        vorher = self._letzt
        if leistung_w is None:
            self._letzt = None
            if vorher is None or self.methode != METHODE_LINKS:
                return 0.0
            return self._buche(vorher, t, vorher[1])
        self._letzt = (t, max(0.0, float(leistung_w)), kategorie)
        if vorher is None:
            return 0.0
        ende = vorher[1] if self.methode == METHODE_LINKS else self._letzt[1]
        return self._buche(vorher, t, ende)

    def _buche(
        self, start: tuple[float, float, str | None], t: float, ende_w: float
    ) -> float:
        dt = t - start[0]
        if dt <= 0 or dt > self.max_luecke_s:
            return 0.0
        mittel_w = (start[1] + ende_w) / 2.0
        kwh = mittel_w * dt / 3_600_000.0
        if kwh <= 0:
            return 0.0
        self.summen[GESAMT] += kwh
        teil = start[2]
        if teil in (HEIZEN, WARMWASSER):
            self.summen[teil] += kwh
        return kwh


class VerdichterZaehler:
    """Zaehlt Verdichterstarts und summiert die Laufzeit (Stunden).

    Ein Start ist der Wechsel der Frequenz par20 von 0 auf > 0. Fehlt par20 in
    einem einzelnen Abruf (``None``), gilt der letzte bekannte Wert weiter -
    sonst wuerde jeder Aussetzer im Portal als neuer Start gezaehlt. Der erste
    Messpunkt nach einem Neustart zaehlt nie als Start: Ob der Verdichter
    vorher stand, weiss man nicht.
    """

    def __init__(self, max_luecke_s: float = MAX_LUECKE_VERDICHTER_S) -> None:
        self.max_luecke_s = float(max_luecke_s)
        self.starts = 0
        self.laufzeit_h = 0.0
        self._letzt_t: float | None = None
        self._letzt_laeuft: bool | None = None

    def uebernehme(self, starts: Any = None, laufzeit_h: Any = None) -> None:
        """Wiederhergestellte Staende addieren (siehe EnergieZaehler.uebernehme)."""
        try:
            if starts is not None and float(starts) > 0:
                self.starts += int(round(float(starts)))
        except (TypeError, ValueError):
            pass
        try:
            if laufzeit_h is not None and float(laufzeit_h) > 0:
                self.laufzeit_h += float(laufzeit_h)
        except (TypeError, ValueError):
            pass

    def messpunkt(self, t: float, frequenz: Any) -> bool:
        """Neuer Messpunkt. Liefert True, wenn sich ein Zaehler geaendert hat."""
        try:
            laeuft: bool | None = None if frequenz is None else float(frequenz) > 0
        except (TypeError, ValueError):
            laeuft = None

        geaendert = False
        if self._letzt_t is not None and self._letzt_laeuft:
            dt = t - self._letzt_t
            if 0 < dt <= self.max_luecke_s:
                self.laufzeit_h += dt / 3600.0
                geaendert = True

        if laeuft is None:
            # Wert fehlt: Zeitpunkt fortschreiben, Zustand behalten
            if self._letzt_t is not None:
                self._letzt_t = t
            return geaendert

        if laeuft and self._letzt_laeuft is False:
            self.starts += 1
            geaendert = True
        self._letzt_t = t
        self._letzt_laeuft = laeuft
        return geaendert
