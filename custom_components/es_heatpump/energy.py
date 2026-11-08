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
  Ist ein Stromzaehler (``energy_entity``, kWh) konfiguriert, werden statt
  dessen dessen Zaehlerstands-Zuwaechse uebernommen (``ZaehlerstandFolger``,
  v4.0.1) - genauer als jede Integration der Leistung.
* **thermisch** - die berechnete Waermeleistung (wie ``ThermLeistungSensor``)
  bei jedem Portalabruf, per Trapezregel.
* **Verdichter** - Starts (Wechsel der Frequenz par20 von 0 auf > 0) und
  Laufzeit (Zeit mit par20 > 0). Seit v4.1.0 dazu ein Ringpuffer der letzten
  Starts und Zykluslaengen fuer die Takt-Erkennung (``VerdichterZaehler.taktet``).
* **Standby** (v4.1.0) - elektrische Energie, waehrend der Verdichter steht
  (par20 == 0): Steuerung, Umwaelzpumpe, Kurbelwannenheizung. Ein Querschnitt
  zur Aufteilung nach Betriebsart, kein weiterer Teil der Summe.

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
from collections import deque
from typing import Any

from .const import (
    CALC_CARNOT,
    CALC_COP,
    CALC_ELEC_POWER,
    CALC_THERM_LEISTUNG,
    CONF_ENERGY_ENTITY,
    CONF_POWER_ENTITY,
    DOMAIN,
    TEMP_SENTINEL,
    WATER_VOL_HEAT_CAPACITY_WH,
)
from .flow import active_flow_rate

# Schluessel der Teilzaehler
GESAMT = "gesamt"
HEIZEN = "heizen"
WARMWASSER = "warmwasser"
# Querschnitt: elektrische Energie bei stehendem Verdichter (v4.1.0). Steht
# zusaetzlich zu GESAMT und ggf. HEIZEN/WARMWASSER, ist also kein Summand.
STANDBY = "standby"
TEILE = (GESAMT, HEIZEN, WARMWASSER, STANDBY)

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
    ("energie_elektrisch_standby", ART_ELEKTRISCH, STANDBY),
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

# Einheiten eines Stromzaehlers (klein geschrieben) -> Faktor auf kWh
_ENERGIE_IN_KWH = {"wh": 0.001, "kwh": 1.0, "mwh": 1000.0, "gwh": 1e6}

# Hoechste glaubwuerdige mittlere Leistung zwischen zwei Zaehlerstaenden. Ein
# groesserer Sprung ist kein Verbrauch, sondern ein getauschter Zaehler oder ein
# Fehlwert - er wird verworfen und der neue Stand als Basis genommen.
MAX_LEISTUNG_ZAEHLER_W = 50_000.0
# Zuschlag fuer kurze Abstaende (Rundung der Zaehlerstaende, Sekundenabstand)
_TOLERANZ_ZAEHLER_KWH = 0.05


def kategorie_von(betriebsart: str | None) -> str | None:
    """Teilzaehler fuer eine Betriebsart; ``None`` = nur Gesamtsumme."""
    if betriebsart is None:
        return None
    return _KATEGORIE.get(betriebsart)


def verdichter_steht(frequenz: Any) -> bool:
    """True nur bei bekannter Verdichterfrequenz par20 <= 0.

    Fehlt der Wert, gilt der Verdichter NICHT als stehend - ein Aussetzer im
    Portal soll keine Energie in den Standby-Zaehler verschieben.
    """
    if frequenz is None:
        return False
    try:
        wert = float(frequenz)
    except (TypeError, ValueError):
        return False
    return math.isfinite(wert) and wert <= 0


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


def energie_in_kwh(roh: Any, einheit: str | None = None) -> float | None:
    """Zaehlerstand einer Energie-Entity in kWh (Wh/kWh/MWh werden umgerechnet).

    ``unknown``/``unavailable`` und alles Nicht-Numerische ergeben ``None``.
    Ohne Einheit gilt kWh. Eine unbekannte Einheit ergibt ``None`` - lieber
    nichts zaehlen als mit einem falschen Faktor.
    """
    if roh in (None, "", "unknown", "unavailable"):
        return None
    try:
        wert = float(roh)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(wert):
        return None
    faktor = _ENERGIE_IN_KWH.get(str(einheit or "kWh").strip().lower())
    if faktor is None:
        return None
    return wert * faktor


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


# ── Carnot-Guetegrad (v4.1.0) ────────────────────────────────────────────
#
# Offsets wie bei heatpumpmonitor.org (OpenEnergyMonitor, emoncms-App "My Heat
# Pump", Kennzahl "Practical Carnot COP"): Die Kondensation liegt etwa 2 K
# ueber dem Vorlauf, die Verdampfung etwa 6 K unter der Aussenluft.
CARNOT_OFFSET_KONDENSATION_K = 2.0
CARNOT_OFFSET_VERDAMPFUNG_K = -6.0
# Kleinster Temperaturhub, fuer den der Carnot-COP noch gerechnet wird. Darunter
# strebt er gegen unendlich und der Guetegrad gegen 0 - eine Zahl ohne Aussage.
CARNOT_MIN_HUB_K = 1.0
_KELVIN = 273.15


def cop_carnot(t_vorlauf: Any, t_aussen: Any) -> float | None:
    """Praktischer Carnot-COP aus Vorlauf- und Aussentemperatur (in °C).

    COP_Carnot = (T_vor + 2 + 273,15) / ((T_vor + 2) - (T_aussen - 6))

    ``None``, wenn ein Wert fehlt, kein gueltiger Messwert ist (-99) oder der
    Nenner nicht groesser als ``CARNOT_MIN_HUB_K`` ist.
    """
    try:
        vor = float(t_vorlauf)
        aussen = float(t_aussen)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(vor) and math.isfinite(aussen)):
        return None
    if vor <= TEMP_SENTINEL or aussen <= TEMP_SENTINEL:
        return None
    kondensation = vor + CARNOT_OFFSET_KONDENSATION_K
    verdampfung = aussen + CARNOT_OFFSET_VERDAMPFUNG_K
    hub = kondensation - verdampfung
    if hub <= CARNOT_MIN_HUB_K:
        return None
    return (kondensation + _KELVIN) / hub


def carnot_guetegrad(
    cop: Any, t_vorlauf: Any, t_aussen: Any, verdichter_laeuft: bool | None
) -> tuple[float | None, float | None]:
    """``(Guetegrad in %, COP_Carnot)`` - Guetegrad = COP / COP_Carnot x 100.

    Guetegrad ``None``, solange der Verdichter nicht laeuft, der COP fehlt
    oder nicht positiv ist, oder der Carnot-COP nicht bestimmbar ist. Der
    Carnot-COP selbst kommt auch ohne laufenden Verdichter zurueck (als
    Attribut aufschlussreich).
    """
    ideal = cop_carnot(t_vorlauf, t_aussen)
    if not verdichter_laeuft or ideal is None:
        return None, ideal
    try:
        wert = float(cop)
    except (TypeError, ValueError):
        return None, ideal
    if not math.isfinite(wert) or wert <= 0:
        return None, ideal
    return wert / ideal * 100.0, ideal


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
        # (Zeit, Leistung W, Kategorie, Standby) des letzten Messpunkts
        self._letzt: tuple[float, float, str | None, bool] | None = None

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
        self,
        t: float,
        leistung_w: float | None,
        kategorie: str | None = None,
        standby: bool = False,
    ) -> float:
        """Neuer Messpunkt zur Zeit ``t`` (Sekunden). Liefert die addierten kWh.

        Wie die Kategorie gilt auch ``standby`` (Verdichter steht) fuer das
        Intervall, das mit diesem Messpunkt beginnt.
        """
        vorher = self._letzt
        if leistung_w is None:
            self._letzt = None
            if vorher is None or self.methode != METHODE_LINKS:
                return 0.0
            return self._buche(vorher, t, vorher[1])
        self._letzt = (t, max(0.0, float(leistung_w)), kategorie, bool(standby))
        if vorher is None:
            return 0.0
        ende = vorher[1] if self.methode == METHODE_LINKS else self._letzt[1]
        return self._buche(vorher, t, ende)

    def _buche(
        self, start: tuple[float, float, str | None, bool], t: float, ende_w: float
    ) -> float:
        dt = t - start[0]
        if dt <= 0 or dt > self.max_luecke_s:
            return 0.0
        mittel_w = (start[1] + ende_w) / 2.0
        kwh = mittel_w * dt / 3_600_000.0
        return self.addiere(kwh, start[2], start[3])

    def addiere(
        self, kwh: float, kategorie: str | None = None, standby: bool = False
    ) -> float:
        """Bucht ``kwh`` auf die Summe, ggf. den Teilzaehler der Kategorie und
        - bei stehendem Verdichter - zusaetzlich auf den Standby-Zaehler."""
        if not (kwh > 0) or not math.isfinite(kwh):
            return 0.0
        self.summen[GESAMT] += kwh
        if kategorie in (HEIZEN, WARMWASSER):
            self.summen[kategorie] += kwh
        if standby:
            self.summen[STANDBY] += kwh
        return kwh


class ZaehlerstandFolger:
    """Schreibt einen ``EnergieZaehler`` aus den Staenden eines Stromzaehlers fort.

    Statt die Leistung zu integrieren, wird der Zuwachs zwischen zwei
    Zaehlerstaenden (kWh) uebernommen und - wie bei der Integration - nach der
    Betriebsart zum Zeitpunkt des Zuwachses aufgeteilt.

    * ``None`` (unbekannt/nicht verfuegbar) wird ignoriert; die Basis bleibt.
      Der naechste gueltige Stand liefert den Zuwachs ueber den Ausfall hinweg -
      der Zaehler hat ja weitergezaehlt.
    * Ein kleinerer Stand als die Basis ist ein Zaehlerreset (Shelly neu
      gestartet, Zaehler getauscht): Das Delta wird verworfen, der neue Stand
      wird Basis.
    * Ein Sprung, der einer mittleren Leistung ueber ``max_leistung_w``
      entspraeche, wird ebenso verworfen.

    ``basis`` / ``basis_t`` lassen sich nach einem Neustart wiederherstellen,
    damit der Verbrauch waehrend des Neustarts nicht verloren geht. Die
    Wiederherstellung darf auch nach dem ersten Messpunkt kommen (die
    Entities werden erst nach dem Start der Beobachtung wiederhergestellt);
    sie ersetzt dann die Basis, solange noch kein Zuwachs gebucht wurde.
    """

    def __init__(
        self, zaehler: EnergieZaehler, max_leistung_w: float = MAX_LEISTUNG_ZAEHLER_W
    ) -> None:
        self.zaehler = zaehler
        self.max_leistung_w = float(max_leistung_w)
        self.basis: float | None = None
        self.basis_t: float | None = None
        self._nur_basis = True   # bisher hoechstens ein Stand, nichts gebucht

    def setze_basis(self, stand_kwh: Any, t: Any = None) -> None:
        """Wiederhergestellte Basis uebernehmen (nur vor dem ersten Zuwachs)."""
        if not self._nur_basis:
            return
        try:
            stand = float(stand_kwh)
        except (TypeError, ValueError):
            return
        if not math.isfinite(stand):
            return
        self.basis = stand
        self._nur_basis = False
        try:
            self.basis_t = float(t) if t is not None else None
        except (TypeError, ValueError):
            self.basis_t = None

    def messpunkt(
        self,
        t: float,
        stand_kwh: float | None,
        kategorie: str | None = None,
        standby: bool = False,
    ) -> float:
        """Neuer Zaehlerstand zur Zeit ``t`` (Sekunden). Liefert die addierten kWh.

        Kategorie und ``standby`` gelten - wie bisher die Kategorie - fuer den
        Zeitpunkt des Zuwachses.
        """
        if stand_kwh is None:
            return 0.0
        vorher, vorher_t = self.basis, self.basis_t
        self.basis, self.basis_t = float(stand_kwh), float(t)
        if vorher is None:
            return 0.0
        self._nur_basis = False
        delta = self.basis - vorher
        if delta <= 0:
            # Gleichstand oder Zaehlerreset: nichts buchen, neuer Stand ist Basis
            return 0.0
        if vorher_t is not None:
            dt_h = max(0.0, t - vorher_t) / 3600.0
            if delta > self.max_leistung_w / 1000.0 * dt_h + _TOLERANZ_ZAEHLER_KWH:
                return 0.0
        return self.zaehler.addiere(delta, kategorie, standby)


# ── Takt-Erkennung (v4.1.0) ──────────────────────────────────────────────
#
# Hoechstens TAKT_MAX_STARTS_JE_STUNDE Starts in der letzten Stunde gelten als
# unauffaellig. Begruendung fuer 3: Hersteller von Scroll- und
# Rotationsverdichtern nennen ueblicherweise 3 (bis 6) Starts je Stunde als
# Obergrenze, und die meisten Waermepumpenregler setzen das ueber eine
# Wiedereinschaltsperre von rund 20 Minuten durch - mehr als drei Starts in
# einer Stunde schafft eine Anlage mit intakter Sperre also gar nicht. Wer
# trotzdem darueber liegt, hat eine Ursache, die sich zu suchen lohnt
# (Heizkurve zu hoch, Hysterese zu klein, zu wenig Wasservolumen).
TAKT_MAX_STARTS_JE_STUNDE = 3
TAKT_FENSTER_S = 3600.0
# Zweites Kriterium: mittlere Laufzeit der letzten Zyklen. Unter etwa 10
# Minuten erreicht der Kreisprozess kaum seinen stationaeren Zustand, Oel und
# Kaeltemittel verteilen sich nicht - Verschleiss ohne nennenswerten Ertrag.
TAKT_MIN_LAUFZEIT_MIN = 10.0
TAKT_ZYKLEN = 3
# Das Laufzeit-Kriterium gilt nur, solange der juengste gewertete Zyklus vor
# hoechstens TAKT_ZYKLEN_MAX_ALTER_S endete. Sonst bliebe der Binaersensor nach
# drei kurzen Zyklen beliebig lange "an" - auch wenn der Verdichter danach
# tagelang steht oder seit Stunden durchlaeuft, also gerade NICHT taktet.
# Sechs Stunden decken eine Nacht mit langen Pausen zwischen kurzen Zyklen ab.
TAKT_ZYKLEN_MAX_ALTER_S = 6 * 3600.0
# Groesse der Ringpuffer. Starts: genug, um mehr als N Starts in einer Stunde
# zu sehen, auch bei sehr kurzen Zyklen.
_RING_STARTS = 32
_RING_ZYKLEN = 10


class VerdichterZaehler:
    """Zaehlt Verdichterstarts und summiert die Laufzeit (Stunden).

    Ein Start ist der Wechsel der Frequenz par20 von 0 auf > 0. Fehlt par20 in
    einem einzelnen Abruf (``None``), gilt der letzte bekannte Wert weiter -
    sonst wuerde jeder Aussetzer im Portal als neuer Start gezaehlt. Der erste
    Messpunkt nach einem Neustart zaehlt nie als Start: Ob der Verdichter
    vorher stand, weiss man nicht.

    Fuer die Takt-Erkennung (v4.1.0) merkt sich der Zaehler die Zeitpunkte der
    letzten Starts und die Laenge der letzten abgeschlossenen Laufzyklen in
    Ringpuffern. Diese ueberdauern einen Neustart nicht - nach einem Neustart
    meldet ``taktet`` also fruehestens wieder, wenn genug Starts bzw. Zyklen
    beobachtet wurden. Ein Zyklus, in den eine Luecke faellt oder dessen
    Beginn man nicht gesehen hat, wird nicht gewertet.
    """

    def __init__(self, max_luecke_s: float = MAX_LUECKE_VERDICHTER_S) -> None:
        self.max_luecke_s = float(max_luecke_s)
        self.starts = 0
        self.laufzeit_h = 0.0
        self._letzt_t: float | None = None
        self._letzt_laeuft: bool | None = None
        # Ringpuffer fuer die Takt-Erkennung
        self._start_zeiten: deque[float] = deque(maxlen=_RING_STARTS)
        self._zyklen_s: deque[float] = deque(maxlen=_RING_ZYKLEN)
        self._zyklus_start: float | None = None
        # Ende des juengsten gewerteten Zyklus (Altersgrenze fuer ``taktet``)
        self._letztes_zyklus_ende: float | None = None

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
            else:
                # Luecke mitten im Lauf: Die Zykluslaenge ist nicht bekannt
                self._zyklus_start = None

        if laeuft is None:
            # Wert fehlt: Zeitpunkt fortschreiben, Zustand behalten
            if self._letzt_t is not None:
                self._letzt_t = t
            return geaendert

        if laeuft and self._letzt_laeuft is False:
            self.starts += 1
            geaendert = True
            self._start_zeiten.append(float(t))
            self._zyklus_start = float(t)
        elif not laeuft and self._letzt_laeuft:
            # Stopp: abgeschlossenen Zyklus merken, sofern sein Beginn bekannt ist
            if self._zyklus_start is not None and t > self._zyklus_start:
                self._zyklen_s.append(float(t) - self._zyklus_start)
                self._letztes_zyklus_ende = float(t)
            self._zyklus_start = None
        self._letzt_t = t
        self._letzt_laeuft = laeuft
        return geaendert

    def starts_seit(self, t: float, fenster_s: float = TAKT_FENSTER_S) -> int:
        """Anzahl der beobachteten Starts im Fenster ``(t - fenster_s, t]``."""
        grenze = t - fenster_s
        return sum(1 for s in self._start_zeiten if grenze < s <= t)

    def mittlere_laufzeit_min(self, anzahl: int = TAKT_ZYKLEN) -> float | None:
        """Mittlere Laenge der letzten ``anzahl`` Zyklen in Minuten.

        ``None``, solange weniger als ``anzahl`` Zyklen beobachtet wurden.
        """
        if anzahl <= 0 or len(self._zyklen_s) < anzahl:
            return None
        letzte = list(self._zyklen_s)[-anzahl:]
        return sum(letzte) / len(letzte) / 60.0

    def taktet(
        self,
        t: float,
        max_starts: int = TAKT_MAX_STARTS_JE_STUNDE,
        min_laufzeit_min: float = TAKT_MIN_LAUFZEIT_MIN,
    ) -> bool:
        """True bei mehr als ``max_starts`` Starts in der letzten Stunde ODER
        einer mittleren Laufzeit der letzten Zyklen unter ``min_laufzeit_min``.

        Das Laufzeit-Kriterium zaehlt nur, solange der juengste Zyklus vor
        hoechstens ``TAKT_ZYKLEN_MAX_ALTER_S`` endete.
        """
        if self.starts_seit(t) > max_starts:
            return True
        ende = self._letztes_zyklus_ende
        if ende is None or t - ende > TAKT_ZYKLEN_MAX_ALTER_S:
            return False
        mittel = self.mittlere_laufzeit_min()
        return mittel is not None and mittel < min_laufzeit_min


# ─────────────────────────────────────────────────────────────────────────────
# Quellen der Auswertungskarte (WebSocket es_heatpump/analysis_config, v4.0.1)
# ─────────────────────────────────────────────────────────────────────────────

# Schluessel der Karte -> Slug des Zaehlers (unique_id-Endung "calc_<slug>")
ANALYSE_ZAEHLER = {
    "el": "energie_elektrisch",
    "el_heat": "energie_elektrisch_heizen",
    "el_dhw": "energie_elektrisch_warmwasser",
    "el_standby": "energie_elektrisch_standby",
    "th": "energie_thermisch",
    "th_heat": "energie_thermisch_heizen",
    "th_dhw": "energie_thermisch_warmwasser",
    "starts": "verdichter_starts",
    "runtime": "verdichter_laufzeit",
}
# Weitere Reihen der Karte -> (unique_id-Endung, Standard-Slug)
ANALYSE_REIHEN = {
    "electrical_power": (CALC_ELEC_POWER, "leistung_elektrisch"),
    "thermal_power": (CALC_THERM_LEISTUNG, "thermische_leistung"),
    "outdoor": ("par24", "aussentemp_ta"),
    "cop": (CALC_COP, "aktueller_cop"),
    "flow": ("par4", "vorlauf_tuo"),
    "carnot": (CALC_CARNOT, "carnot_guetegrad"),
}
# Binaersensoren (v4.1.0): Schluessel der Karte -> Slug (unique_id-Endung und
# Entity-ID binary_sensor.es_hp_<slug>)
ANALYSE_BINAER = {
    "verdichter": "verdichter",
    "abtauen": "abtauen",
    "warmwasser": "warmwasserbereitung",
    "takten": "takten",
}


def analyse_konfiguration(
    finde: Any, benutzer: str | None, optionen: dict[str, Any]
) -> dict[str, Any]:
    """Antwort von ``es_heatpump/analysis_config``.

    ``finde(unique_id, plattform)`` liefert die Entity-ID aus der
    Entity-Registry oder ``None``. Die unique_ids lauten
    ``es_heatpump_<benutzer>_<endung>`` (siehe sensor.py, binary_sensor.py);
    hat der Nutzer eine Entity umbenannt, wird sie so trotzdem gefunden. Sonst
    gilt die Standard-ID ``<plattform>.es_hp_<slug>``.
    """
    def eid(endung: str, slug: str, plattform: str = "sensor") -> str:
        if benutzer:
            gefunden = finde(f"{DOMAIN}_{benutzer}_{endung}", plattform)
            if gefunden:
                return gefunden
        return f"{plattform}.es_hp_{slug}"

    antwort: dict[str, Any] = {k: eid(*v) for k, v in ANALYSE_REIHEN.items()}
    antwort["counters"] = {
        k: eid(f"calc_{slug}", slug) for k, slug in ANALYSE_ZAEHLER.items()
    }
    antwort["binary"] = {
        k: eid(slug, slug, "binary_sensor") for k, slug in ANALYSE_BINAER.items()
    }
    antwort["energy_entity"] = optionen.get(CONF_ENERGY_ENTITY) or None
    antwort["power_entity"] = optionen.get(CONF_POWER_ENTITY) or None
    return antwort
