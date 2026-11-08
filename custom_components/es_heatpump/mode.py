"""Operating-mode detection for the ES Heatpump integration.

Deliberately free of Home Assistant imports so the rules can be unit-tested
without a running HA instance — see ``tests/test_mode.py``.

Background
----------
The myheatpump.com portal API has no clean operating-mode field. ``par15`` was
assumed to be one in v2.0.0–v2.2.0, but live observation showed it toggles 0/1
every ten minutes regardless of the mode shown in the portal HTML: a heartbeat,
not a mode. v2.2.1 therefore required an external helper entity (typically a
multiscrape sensor reading the portal's "Unit Current Working Mode").

Since v2.4.0 none of that is needed: the portal's form page names ``par1`` as
"Unit Current Working Mode" and supplies the meanings as <select> options —
and ``par1`` sits in the very JSON endpoint the integration has always polled.
It was simply never mapped. The derivation below stays as a fallback for
devices that do not report ``par1``, and it keeps doing one thing ``par1``
cannot: the portal's list has no defrost state, because defrosting is not a
mode but an event inside heating.

The older derivation, retained as fallback: during hot-water production the
machine drives the flow far above whatever the heating circuit currently asks
for. That holds for underfloor heating (flow ≈33 °C) and radiators (flow
≈50 °C) alike, where a fixed threshold would misclassify one of them.

Korrektur 22.09.2026 (v3.0.0)
-----------------------------
Bis v2.5.0 verglich die Ableitung gegen ``par6``, im Glauben, das sei der
Heizen-Sollwert. Das Anlagenschaubild des Portals nennt ``par6`` **Tup** - eine
gemessene Wassertemperatur. Der Beweis steht in der Historie: ``par6`` faellt in
80 Sekunden um 18 K, sobald die Umwaelzpumpe stehenbleibt, waehrend der Vorlauf
steht. Ein Sollwert tut das nicht.

Die Folge war ein echter Fehler: Kurz nach einem Verdichterstart stand ``par6``
noch bei 14 °C und der Vorlauf bei 32 °C - die Ableitung meldete dann
"Brauchwasser", obwohl geheizt wurde.

Verglichen wird stattdessen gegen ``par8`` - "Cooling/Heating Water Temp. - TC",
die Temperatur des Heizwassers im Puffer. Das ist physikalisch der richtige
Bezug: Bei der Warmwasserbereitung treibt die Maschine den Vorlauf weit ueber
das, was der Heizkreis gerade fuehrt, waehrend der Puffer auf seiner Temperatur
stehen bleibt.

``par8`` hat genau die Eigenschaft, die ``par6`` fehlt: **thermische Traegheit.**
Ein Puffer kuehlt in Minuten um Zehntelgrad aus, nicht um 18 K. Beleg aus
sechs Stunden Historie: ``par8`` blieb durchgehend zwischen 28,2 und 34,0 °C -
auch waehrend einer Warmwasserladung, bei der der Vorlauf auf 58,2 °C stieg.

Der Vergleich gegen eine Wassertemperatur statt gegen einen Sollwert traegt
ausserdem beide Anlagenarten: Fussbodenheizung (Vorlauf ~33 °C, TC ~33 °C) und
Heizkoerper (Vorlauf ~50 °C, TC ~49 °C) liegen beide dicht beieinander, waehrend
der Abstand bei Warmwasser 20 K und mehr betraegt. Eine feste Schwelle koennte
das nicht: Sie muesste unter 50 liegen, um Heizkoerper nicht als Warmwasser zu
lesen, und ueber 50, um Warmwasser ueberhaupt zu erkennen.

Faellt ``par8`` aus, bleibt ``DHW_ABSOLUTE_FALLBACK_C`` als grobe Ersatzschwelle.
"""
from __future__ import annotations

from typing import Any

from .const import (
    BETRIEBSART_ALIASES,
    DEFAULT_DHW_MARGIN_K,
    DEFROST_SPREAD_K,
    DHW_ABSOLUTE_FALLBACK_C,
    PAR1_BETRIEBSART,
    PAR_BETRIEBSART,
    TEMP_SENTINEL,
)

# Parameter ids used by the rules, named for readability
PAR_VORLAUF   = "par4"    # flow temperature (Tuo)
PAR_RUECKLAUF = "par5"    # return temperature (Tui)
PAR_TUP       = "par6"    # Tup - gemessene Wassertemperatur, KEIN Sollwert
PAR_HEIZWASSER = "par8"  # TC - Heizwassertemperatur im Puffer, traege
PAR_FREQUENZ  = "par20"   # compressor frequency in Hz


def usable(value: Any) -> bool:
    """True if a portal temperature is a real reading, not the -99 sentinel."""
    return value is not None and value > TEMP_SENTINEL


def betriebsart_aus_par1(data: dict[str, Any]) -> tuple[str | None, str]:
    """Read the operating mode the unit itself reports.

    Returns ``(mode, reason)`` or ``(None, reason)`` when ``par1`` is missing or
    holds a value the portal does not define.
    """
    roh = data.get(PAR_BETRIEBSART)
    if roh is None:
        return None, f"{PAR_BETRIEBSART} nicht in den Daten"
    try:
        nummer = int(float(roh))
    except (TypeError, ValueError):
        return None, f"{PAR_BETRIEBSART} ist kein Zahlenwert: {roh!r}"
    modus = PAR1_BETRIEBSART.get(nummer)
    if modus is None:
        return None, f"{PAR_BETRIEBSART} = {nummer}, vom Portal nicht definiert"
    return modus, f"Geräteangabe {PAR_BETRIEBSART} = {nummer} ({modus})"


def ist_abtauen(data: dict[str, Any]) -> bool:
    """True while the refrigeration cycle runs in reverse.

    The portal knows no defrost mode — during a defrost cycle it keeps
    reporting "Heating" while the machine pulls heat *out* of the heating
    water. The flow then drops below the return, which no normal heating
    operation does.
    """
    freq, vor, rue = data.get("par20"), data.get(PAR_VORLAUF), data.get(PAR_RUECKLAUF)
    if not freq or freq <= 0:
        return False
    if not usable(vor) or not usable(rue):
        return False
    return (vor - rue) <= DEFROST_SPREAD_K


def derive_betriebsart(
    data: dict[str, Any], dhw_margin_k: float
) -> tuple[str, str]:
    """Derive the operating mode from the heat pump's own values.

    Returns ``(mode, reason)``. The reason is surfaced as a state attribute so
    the decision can be checked in the UI without reading this source.

    Rules, in order:

    1. no compressor frequency in the data   → ``Unbekannt``
    2. compressor standing still             → ``Aus``
    3. flow colder than return               → ``Entfrosten`` (reverse cycle)
    4. flow above setpoint + ``dhw_margin_k`` → ``Brauchwasser``
    5. otherwise                             → ``Heizen``

    Rule 3 has to come before rule 4: during a defrost cycle the machine takes
    heat *out* of the heating water, and a rising flow temperature elsewhere in
    the system must not be mistaken for hot-water production.
    """
    freq = data.get(PAR_FREQUENZ)
    vor  = data.get(PAR_VORLAUF)
    rue  = data.get(PAR_RUECKLAUF)
    heizwasser = data.get(PAR_HEIZWASSER)

    if freq is None:
        return "Unbekannt", "keine Kompressorfrequenz (par20) in den Daten"
    if freq <= 0:
        return "Aus", "Kompressorfrequenz 0 Hz"

    if not usable(vor) or not usable(rue):
        return "Unbekannt", "Vorlauf oder Rücklauf nicht verfügbar"

    spread = vor - rue
    if spread <= DEFROST_SPREAD_K:
        return "Entfrosten", (
            f"Spreizung {spread:.1f} K — Vorlauf kälter als Rücklauf, "
            f"Kreisprozess also umgekehrt"
        )

    if usable(heizwasser):
        schwelle = heizwasser + dhw_margin_k
        herkunft = (
            f"{schwelle:.1f} °C (Heizwasser TC {heizwasser:.1f} °C "
            f"+ {dhw_margin_k:.1f} K)"
        )
    else:
        schwelle = DHW_ABSOLUTE_FALLBACK_C
        herkunft = (
            f"{DHW_ABSOLUTE_FALLBACK_C:.0f} °C (feste Ersatzschwelle, "
            f"Heizwasser par8 nicht verfügbar)"
        )

    if vor > schwelle:
        return "Brauchwasser", f"Vorlauf {vor:.1f} °C über {herkunft}"
    return "Heizen", f"Vorlauf {vor:.1f} °C unter {herkunft}"


# ─────────────────────────────────────────────────────────────────────────────
# Aufloesung der Betriebsart (bis v4.0.1 in sensor.py, seit v4.1.0 hier)
# ─────────────────────────────────────────────────────────────────────────────
#
# Sensoren UND Binaersensoren brauchen dieselbe Betriebsart. Damit es genau eine
# Rechnung samt Zwischenspeicher gibt, steht sie hier. ``hass`` wird nur als
# Objekt mit ``hass.states.get(entity_id)`` gebraucht - das Modul bleibt frei von
# Home-Assistant-Importen und laesst sich mit einem Ersatzobjekt testen.
#
# v2.2.1: par15 galt als Betriebsart, ist aber ein Herzschlag (wechselt alle
# ~10 min zwischen 0 und 1). Die externe Entity (``mode_source_entity``) ist
# seitdem die optionale Quelle, wenn das Geraet kein par1 meldet.

_NUMERIC_MODE_MAP = {0: "Aus", 1: "Brauchwasser", 2: "Heizen", 3: "Entfrosten"}
_PAREN_NUMBER_RE = __import__("re").compile(r"\(([-+]?\d+(?:\.\d+)?)\)")


def mode_from_source(hass: Any, mode_source: str | None) -> str:
    """Betriebsart aus einer externen Hilfs-Entity (optionaler Vorrang)."""
    if not mode_source:
        return "Unbekannt"
    state = hass.states.get(mode_source)
    if state is None or state.state in ("unknown", "unavailable", ""):
        return "Unbekannt"
    raw = str(state.state).strip().lower()

    # Bekannte Schreibweisen
    if raw in BETRIEBSART_ALIASES:
        return BETRIEBSART_ALIASES[raw]

    # Multiscrape-Form "Unbekannt (0.0)" / "Unknown (2.0)" - die Zahl in den
    # Klammern auswerten.
    m = _PAREN_NUMBER_RE.search(raw)
    if m:
        try:
            as_int = int(float(m.group(1)))
            if as_int in _NUMERIC_MODE_MAP:
                return _NUMERIC_MODE_MAP[as_int]
        except (ValueError, TypeError):
            pass

    # Reine Zahl (Quellen im Stil von par15)
    try:
        as_int = int(float(raw))
        if as_int in _NUMERIC_MODE_MAP:
            return _NUMERIC_MODE_MAP[as_int]
    except (ValueError, TypeError):
        pass
    return "Unbekannt"


# Zwischenspeicher fuer resolve_betriebsart (v4.0.1). Bis zu acht Entities
# fragten je Abruf dieselbe Betriebsart ab, jede rechnete sie vollstaendig neu.
# Schluessel: Datenstand des Koordinators (Objekt-Identitaet, gegen
# Wiederverwendung der id() durch die mitgehaltene Referenz abgesichert),
# Optionen und Zustand der externen Betriebsart-Entity. Das Ergebnis ist damit
# exakt dasselbe wie ohne Zwischenspeicher.
_BETRIEBSART_CACHE: dict[tuple, tuple[Any, tuple[str, str]]] = {}
_BETRIEBSART_CACHE_MAX = 32


def resolve_betriebsart(
    hass: Any,
    mode_source: str | None,
    data: dict[str, Any] | None = None,
    dhw_margin_k: float = DEFAULT_DHW_MARGIN_K,
) -> tuple[str, str]:
    """Wie ``resolve_betriebsart_neu``, aber je Datenstand nur einmal gerechnet."""
    if not data:
        return resolve_betriebsart_neu(hass, mode_source, data, dhw_margin_k)
    quelle_zustand = None
    if mode_source:
        state = hass.states.get(mode_source)
        quelle_zustand = state.state if state is not None else None
    schluessel = (id(data), mode_source, dhw_margin_k, quelle_zustand)
    treffer = _BETRIEBSART_CACHE.get(schluessel)
    if treffer is not None and treffer[0] is data:
        return treffer[1]
    ergebnis = resolve_betriebsart_neu(hass, mode_source, data, dhw_margin_k)
    if len(_BETRIEBSART_CACHE) >= _BETRIEBSART_CACHE_MAX:
        _BETRIEBSART_CACHE.clear()
    _BETRIEBSART_CACHE[schluessel] = (data, ergebnis)
    return ergebnis


def resolve_betriebsart_neu(
    hass: Any,
    mode_source: str | None,
    data: dict[str, Any] | None = None,
    dhw_margin_k: float = DEFAULT_DHW_MARGIN_K,
) -> tuple[str, str]:
    """Kanonische Betriebsart, als zweites Element die Begruendung.

    Rangfolge:

    1. **``par1``** - die Geraeteangabe "Unit Current Working Mode" (seit
       v2.4.0). Massgeblich, weil die Maschine sie selbst meldet.
    2. **``mode_source_entity``** - die externe Hilfs-Entity aus der Zeit vor
       v2.4.0. Sie liest dieselbe Angabe aus dem Portal-HTML und gilt nur, wenn
       par1 fehlt.
    3. **Ableitung** aus Frequenz, Spreizung und Vorlauf gegen Heizwasser
       (v2.3.0) - der Rueckfall fuer Geraete ohne par1.

    Dazu: Abtauen kennt das Portal nicht als Betriebsart. Waehrend der
    Kreisprozess umgekehrt laeuft, meldet das Geraet weiter "Heizen"; dieser
    Fall wird hier korrigiert.
    """
    data = data or {}

    modus, grund = betriebsart_aus_par1(data)
    if modus is None and mode_source:
        extern = mode_from_source(hass, mode_source)
        if extern != "Unbekannt":
            modus, grund = extern, f"externe Entity {mode_source} meldet {extern}"
    if modus is None and data:
        modus, grund = derive_betriebsart(data, dhw_margin_k)
    if modus is None:
        return "Unbekannt", grund

    if modus in ("Heizen", "Brauchwasser + Heizen") and ist_abtauen(data):
        return "Entfrosten", (
            f"{grund}, aber Vorlauf unter Rücklauf — Kreisprozess umgekehrt"
        )
    return modus, grund


# ─────────────────────────────────────────────────────────────────────────────
# Zustaende der Binaersensoren (v4.1.0)
# ─────────────────────────────────────────────────────────────────────────────

# Betriebsarten, in denen das Umschaltventil zum Warmwasserspeicher steht
WARMWASSER_BETRIEBSARTEN = frozenset({
    "Brauchwasser", "Brauchwasser + Heizen", "Brauchwasser + Kuehlen",
})


def verdichter_laeuft(data: dict[str, Any] | None) -> bool | None:
    """True bei Verdichterfrequenz par20 > 0; ``None``, wenn par20 fehlt."""
    roh = (data or {}).get(PAR_FREQUENZ)
    if roh is None:
        return None
    try:
        return float(roh) > 0
    except (TypeError, ValueError):
        return None


def ist_warmwasserbereitung(betriebsart: str | None) -> bool | None:
    """Warmwasserbereitung laut aufgeloester Betriebsart; ``None`` = unbekannt."""
    if betriebsart in (None, "Unbekannt"):
        return None
    return betriebsart in WARMWASSER_BETRIEBSARTEN


def ist_entfrosten(betriebsart: str | None) -> bool | None:
    """Abtauen laut aufgeloester Betriebsart; ``None`` = unbekannt.

    ``resolve_betriebsart`` hat ``ist_abtauen`` (Vorlauf unter Ruecklauf bei
    laufendem Verdichter) dann schon beruecksichtigt - fuer die Ableitung ohne
    par1 ebenso wie als Korrektur einer Geraeteangabe "Heizen".
    """
    if betriebsart in (None, "Unbekannt"):
        return None
    return betriebsart == "Entfrosten"
