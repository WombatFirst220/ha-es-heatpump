"""Volumetric-flow resolution for the ES Heatpump integration.

Free of Home Assistant imports so the rules stay unit-testable — see
``tests/test_flow.py``.

Why this module exists
----------------------
The heat pump neither measures nor reports its water flow. Thermal output and
COP are therefore calculated from a configured constant. That is only exact if
the circulation pump runs at a fixed speed.

On the AWC-R32-M-V8 the loop is driven by the built-in pump P0 in the outdoor
unit. According to the ES installation manual ("R32 V8 Series" v3.1) P0 is
either an AC pump (on/off only) or a PWM pump with one fixed step (High /
Middle / Low) per mode - there is no load- or spread-based control. The flow is
therefore roughly constant per mode, and heating and DHW share the same pump:
the DHW flow is about the heating flow unless the display shows a different
pump step (v4.1.1). A heating-circuit pump behind a buffer tank does not change
the flow through the heat pump.

Since v2.3.1 a live flow sensor can be configured instead; the constant is only
the fallback.
"""
from __future__ import annotations

from typing import Any

from .const import (
    DEFAULT_FLOW_RATE,
    DEFAULT_FLOW_RATE_DHW,
    FLOW_ENTITY_UNITS_TO_M3H,
    NOMINAL_FLOW_RATES_M3H,
)


def nennvolumenstroeme(
    modell: str | None,
    eingabe: dict[str, Any],
    vorher_modell: str | None = None,
    *,
    nur_standardwerte: bool = False,
) -> dict[str, float]:
    """Volumenstroeme, die die Modellwahl setzen soll (v4.1.1).

    Liefert ``{"flow_rate": x, "flow_rate_dhw": x}`` mit dem Nennwert des
    Datenblatts, oder ein leeres dict, wenn nichts zu setzen ist:

    - unbekanntes Modell: nichts;
    - Optionen (``nur_standardwerte=False``): nur wenn das Modell gewechselt
      hat - danach bleiben beide Werte von Hand anpassbar;
    - Einrichtung (``nur_standardwerte=True``): nur Felder, die noch auf dem
      Standardwert stehen, damit eine bewusste Eingabe nicht verloren geht.

    Beide Kreise bekommen denselben Wert, weil P0 Heiz- und Warmwasserkreis
    versorgt. Bis v4.1.0 blieb der Warmwasser-Wert auf 1,0 m³/h stehen und
    ergab bei einer AWC12 Warmwasser-COPs unter 1.
    """
    if modell not in NOMINAL_FLOW_RATES_M3H:
        return {}
    nenn = NOMINAL_FLOW_RATES_M3H[modell][1]
    if nur_standardwerte:
        neu: dict[str, float] = {}
        for key, standard in (("flow_rate", DEFAULT_FLOW_RATE),
                              ("flow_rate_dhw", DEFAULT_FLOW_RATE_DHW)):
            wert = eingabe.get(key, standard)
            if wert is None or float(wert) == float(standard):
                neu[key] = nenn
        return neu
    if modell == vorher_modell:
        return {}
    return {"flow_rate": nenn, "flow_rate_dhw": nenn}


def flow_from_entity(state: Any) -> tuple[float | None, str]:
    """Convert a flow-sensor state to m³/h.

    ``state`` is anything with ``.state`` and ``.attributes`` (a Home Assistant
    state object) or ``None``. Returns ``(value_m3h, reason)``; ``value`` is
    ``None`` when the entity cannot be used, and the reason says why.
    """
    if state is None:
        return None, "Volumenstrom-Entity nicht gefunden"
    roh = getattr(state, "state", None)
    if roh in (None, "unknown", "unavailable", ""):
        return None, f"Volumenstrom-Entity liefert '{roh}'"
    try:
        wert = float(roh)
    except (TypeError, ValueError):
        return None, f"Volumenstrom-Entity liefert keinen Zahlenwert: {roh!r}"
    if wert < 0:
        return None, f"Volumenstrom negativ ({wert})"

    einheit = (getattr(state, "attributes", {}) or {}).get("unit_of_measurement")
    faktor = FLOW_ENTITY_UNITS_TO_M3H.get(einheit)
    if faktor is None:
        # Ohne bekannte Einheit m³/h annehmen, aber in der Begruendung sagen
        return wert, (
            f"{wert:g} (Einheit {einheit!r} unbekannt, als m³/h gewertet)"
        )
    return wert * faktor, f"{wert:g} {einheit} = {wert * faktor:.3f} m³/h"


def active_flow_rate(
    mode: str,
    flow_heating: float,
    flow_dhw: float,
    live_flow: float | None = None,
) -> float:
    """Volumetric flow to use for the current mode, in m³/h.

    A live sensor value wins over the configured constants whenever the machine
    is actually running — it is a measurement, the constants are assumptions.
    In "Aus" and "Entfrosten" no useful heat is delivered, so the flow is 0
    regardless of what a sensor reports.
    """
    # Kein nutzbarer Waermeeintrag ins Heizsystem:
    #   Aus          - Kompressor steht
    #   Entfrosten   - Kreisprozess laeuft rueckwaerts, Waerme wird entzogen
    #   Kuehlen      - Kaelteleistung, nicht Waermeleistung; die Integration
    #                  rechnet sie (noch) nicht, lieber 0 als ein falsches
    #                  Vorzeichen
    if mode in ("Aus", "Entfrosten", "Kuehlen", "Brauchwasser + Kuehlen"):
        return 0.0
    if live_flow is not None and live_flow > 0:
        return live_flow
    if mode == "Brauchwasser":
        return flow_dhw
    # "Heizen", "Brauchwasser + Heizen" und "Unbekannt": der Heizkreis laeuft,
    # er ist der groessere Verbraucher und der besser bekannte Wert.
    return flow_heating
