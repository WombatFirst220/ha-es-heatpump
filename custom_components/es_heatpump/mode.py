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

The older derivation, retained as fallback: The
decisive insight is to compare the flow temperature against the *heating
setpoint* (par6) rather than an absolute threshold: during hot-water production
the machine drives the flow far above whatever the heating circuit currently
asks for. That holds for underfloor heating (flow ≈33 °C) and radiators
(flow ≈50 °C) alike, where a fixed threshold would misclassify one of them.
"""
from __future__ import annotations

from typing import Any

from .const import (
    DEFROST_SPREAD_K,
    DHW_ABSOLUTE_FALLBACK_C,
    PAR1_BETRIEBSART,
    PAR_BETRIEBSART,
    TEMP_SENTINEL,
)

# Parameter ids used by the rules, named for readability
PAR_VORLAUF   = "par4"    # flow temperature (Tuo)
PAR_RUECKLAUF = "par5"    # return temperature (Tui)
PAR_SOLL      = "par6"    # heating setpoint
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
    soll = data.get(PAR_SOLL)

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

    if usable(soll):
        schwelle = soll + dhw_margin_k
        if vor > schwelle:
            return "Brauchwasser", (
                f"Vorlauf {vor:.1f} °C über Heizen-Soll {soll:.1f} °C "
                f"+ {dhw_margin_k:.1f} K = {schwelle:.1f} °C"
            )
        return "Heizen", (
            f"Vorlauf {vor:.1f} °C unter Schwelle {schwelle:.1f} °C "
            f"(Heizen-Soll {soll:.1f} °C + {dhw_margin_k:.1f} K)"
        )

    # No usable setpoint — fall back to an absolute threshold
    if vor > DHW_ABSOLUTE_FALLBACK_C:
        return "Brauchwasser", (
            f"Vorlauf {vor:.1f} °C über {DHW_ABSOLUTE_FALLBACK_C:.0f} °C "
            f"(Heizen-Soll par6 nicht verfügbar)"
        )
    return "Heizen", (
        f"Vorlauf {vor:.1f} °C unter {DHW_ABSOLUTE_FALLBACK_C:.0f} °C "
        f"(Heizen-Soll par6 nicht verfügbar)"
    )
