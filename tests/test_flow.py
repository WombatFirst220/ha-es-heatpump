"""Tests für die Volumenstrom-Auflösung (v2.3.1).

Ohne Home-Assistant-Abhängigkeit, siehe Kopf von tests/test_mode.py.
"""
import importlib.util
import pathlib
import sys
import types

_ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "es_heatpump"
_PKG = "es_heatpump_unter_test_flow"
_paket = types.ModuleType(_PKG)
_paket.__path__ = [str(_ROOT)]
sys.modules[_PKG] = _paket


def _lade(name):
    spec = importlib.util.spec_from_file_location(f"{_PKG}.{name}", _ROOT / f"{name}.py")
    modul = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modul
    spec.loader.exec_module(modul)
    return modul


_const = _lade("const")
_flow = _lade("flow")
flow_from_entity = _flow.flow_from_entity
active_flow_rate = _flow.active_flow_rate
NOMINAL = _const.NOMINAL_FLOW_RATES_M3H


class Zustand:
    """Minimaler Ersatz für ein Home-Assistant-State-Objekt."""
    def __init__(self, state, unit=None):
        self.state = state
        self.attributes = {"unit_of_measurement": unit} if unit else {}


def test_einheiten_werden_umgerechnet():
    for roh, einheit, erwartet in (
        ("2.02", "m³/h", 2.02),
        ("2.02", "m3/h", 2.02),
        ("33.7", "l/min", 2.022),
        ("2020", "l/h", 2.02),
        ("0.56", "l/s", 2.016),
    ):
        wert, grund = flow_from_entity(Zustand(roh, einheit))
        assert wert is not None, grund
        assert abs(wert - erwartet) < 0.01, f"{roh} {einheit}: {wert} statt {erwartet}"


def test_unbrauchbare_zustaende():
    for zustand in (None, Zustand("unavailable"), Zustand("unknown"),
                    Zustand(""), Zustand("kaputt"), Zustand("-1", "m³/h")):
        wert, grund = flow_from_entity(zustand)
        assert wert is None, f"{zustand} haette None ergeben muessen, war {wert}"
        assert grund


def test_unbekannte_einheit_wird_als_m3h_gewertet_und_benannt():
    wert, grund = flow_from_entity(Zustand("1.8", "gpm"))
    assert wert == 1.8
    assert "unbekannt" in grund.lower()


def test_messwert_schlaegt_konstante():
    assert active_flow_rate("Heizen", 2.02, 1.0, live_flow=1.55) == 1.55
    assert active_flow_rate("Brauchwasser", 2.02, 1.0, live_flow=1.55) == 1.55


def test_ohne_messwert_gelten_die_konstanten():
    assert active_flow_rate("Heizen", 2.02, 1.0) == 2.02
    assert active_flow_rate("Brauchwasser", 2.02, 1.0) == 1.0
    assert active_flow_rate("Unbekannt", 2.02, 1.0) == 2.02


def test_ohne_waermeabgabe_null():
    """Aus und Entfrosten liefern 0, auch wenn ein Sensor etwas meldet:
    ein zirkulierender Volumenstrom ist keine abgegebene Waerme."""
    assert active_flow_rate("Aus", 2.02, 1.0, live_flow=2.0) == 0.0
    assert active_flow_rate("Entfrosten", 2.02, 1.0, live_flow=2.0) == 0.0


def test_nennwerte_aus_dem_datenblatt():
    """Umrechnung l/s -> m³/h, gegen die Datenblattzeile geprueft."""
    for modell, ls_min, ls_nom in (
        ("AWC6-R32-M-V8", 0.18, 0.28), ("AWC9-R32-M-V8", 0.26, 0.43),
        ("AWC12-R32-M-V8", 0.40, 0.56), ("AWC15-R32-M-V8", 0.62, 0.72),
        ("AWC19-R32-M-V8", 0.74, 0.91),
    ):
        mn, nom = NOMINAL[modell]
        assert abs(mn - ls_min * 3.6) < 0.01, modell
        assert abs(nom - ls_nom * 3.6) < 0.01, modell


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} Prüfungen bestanden.")
