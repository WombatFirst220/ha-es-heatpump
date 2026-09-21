"""Tests für die Betriebsart-Erkennung (v2.3.0).

Bewusst ohne Home-Assistant-Abhängigkeit: ``custom_components.es_heatpump.mode``
importiert nur aus ``const``, beides reines Python.

Aufruf:  python3 -m pytest tests/ -q
   oder:  python3 tests/test_mode.py
"""
import importlib.util
import pathlib
import sys
import types

# const.py und mode.py direkt laden. Über das Paket zu importieren würde
# custom_components/es_heatpump/__init__.py ausführen, und das braucht eine
# installierte Home-Assistant-Umgebung - genau die soll hier nicht nötig sein.
_ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "es_heatpump"
_PKG = "es_heatpump_unter_test"
_paket = types.ModuleType(_PKG)
_paket.__path__ = [str(_ROOT)]
sys.modules[_PKG] = _paket


def _lade(name):
    spec = importlib.util.spec_from_file_location(f"{_PKG}.{name}", _ROOT / f"{name}.py")
    modul = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modul
    spec.loader.exec_module(modul)
    return modul


DEFAULT_DHW_MARGIN_K = _lade("const").DEFAULT_DHW_MARGIN_K
derive_betriebsart = _lade("mode").derive_betriebsart

M = DEFAULT_DHW_MARGIN_K


def d(freq=None, vor=None, rue=None, soll=None):
    """Kurzschreibweise für einen Portal-Datensatz."""
    return {"par20": freq, "par4": vor, "par5": rue, "par6": soll}


# (Beschreibung, Datensatz, erwartete Betriebsart)
# Die Messwerte stammen aus einer realen AWC12-R32-M-V8 mit Fußbodenheizung
# (Auslegungsvorlauf 35 °C), aufgezeichnet am 21.09.2026.
FAELLE = [
    ("Stillstand nachts",           d(0,   29.2, 29.2, 31.6), "Aus"),
    ("Heizen, Messwert",            d(43,  33.7, 31.7, 31.6), "Heizen"),
    ("Heizen, Median im Betrieb",   d(58,  33.5, 31.2, 31.6), "Heizen"),
    ("Warmwasser, gemessene Spitze",d(70,  58.8, 55.9, 31.6), "Brauchwasser"),
    ("Abtauen, Vorlauf kälter",     d(60,  25.0, 28.0, 31.6), "Entfrosten"),
    # Heizkörperanlage: hoher Vorlauf, aber nahe am Sollwert. Eine absolute
    # Schwelle bei 45 °C würde hier fälschlich Brauchwasser erkennen - der
    # Vergleich gegen den Sollwert nicht.
    ("Heizkörper 50 °C",            d(55,  50.0, 46.0, 49.0), "Heizen"),
    ("Heizkörper + Warmwasser",     d(70,  62.0, 58.0, 49.0), "Brauchwasser"),
    # Ohne Sollwert greift die absolute Ersatzschwelle
    ("Soll fehlt, Vorlauf 33",      d(50,  33.0, 30.5, -99.0), "Heizen"),
    ("Soll fehlt, Vorlauf 55",      d(70,  55.0, 52.0, -99.0), "Brauchwasser"),
    # Defekte oder fehlende Werte dürfen nicht raten
    ("Vorlauf-Sensor defekt",       d(50, -99.0, 30.0, 31.6), "Unbekannt"),
    ("keine Frequenz im Datensatz", d(None, 33.0, 31.0, 31.6), "Unbekannt"),
]


def test_betriebsart_erkennung():
    for name, daten, erwartet in FAELLE:
        mode, grund = derive_betriebsart(daten, M)
        assert mode == erwartet, f"{name}: {mode} statt {erwartet} ({grund})"


def test_begruendung_ist_immer_gesetzt():
    for _, daten, _ in FAELLE:
        _, grund = derive_betriebsart(daten, M)
        assert grund and isinstance(grund, str)


def test_abtauen_schlaegt_brauchwasser():
    """Rückwärtslaufender Kreisprozess darf nicht als Warmwasser gelten,
    auch wenn der Vorlauf über der Brauchwasser-Schwelle liegt."""
    mode, _ = derive_betriebsart(d(70, 55.0, 60.0, 31.6), M)
    assert mode == "Entfrosten"


def test_margin_wirkt():
    daten = d(60, 40.0, 37.0, 31.6)
    assert derive_betriebsart(daten, 5.0)[0] == "Brauchwasser"   # Schwelle 36,6
    assert derive_betriebsart(daten, 12.0)[0] == "Heizen"        # Schwelle 43,6


if __name__ == "__main__":
    for fn in (test_betriebsart_erkennung, test_begruendung_ist_immer_gesetzt,
               test_abtauen_schlaegt_brauchwasser, test_margin_wirkt):
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(FAELLE)} Fälle und 3 Sonderprüfungen bestanden.")
