"""Volumetric-flow resolution for the ES Heatpump integration.

Free of Home Assistant imports so the rules stay unit-testable — see
``tests/test_flow.py``.

Why this module exists
----------------------
The heat pump neither measures nor reports its water flow. Thermal output and
COP are therefore calculated from a configured constant. That is only exact if
the circulation pump runs at a fixed speed.

Many installations use a pump in proportional-pressure or "Auto" mode, which
raises the flow as the load rises. The constant is then right at one operating
point and wrong everywhere else. The telltale sign is in the data: with a fixed
flow the spread has to grow with the compressor power, and with a modulating
pump it stays roughly flat.

Since v2.3.1 a live flow sensor can be configured instead; the constant is only
the fallback.
"""
from __future__ import annotations

from typing import Any

from .const import FLOW_ENTITY_UNITS_TO_M3H


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
