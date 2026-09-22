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


def _alle_tests():
    return [v for k, v in sorted(globals().items())
            if k.startswith("test_") and callable(v)]


# ── par1: die Geräteangabe (seit v2.4.0) ─────────────────────────────────────

betriebsart_aus_par1 = _lade("mode").betriebsart_aus_par1
ist_abtauen = _lade("mode").ist_abtauen


def test_par1_wird_nach_der_portal_liste_uebersetzt():
    """Werte und Namen stammen aus den <select>-Optionen von
    /a/amt/realdata/form, abgelesen am 22.09.2026."""
    for wert, erwartet in (
        (0, "Aus"), (1, "Brauchwasser"), (2, "Heizen"), (3, "Kuehlen"),
        (4, "Brauchwasser + Heizen"), (5, "Brauchwasser + Kuehlen"),
    ):
        modus, grund = betriebsart_aus_par1({"par1": float(wert)})
        assert modus == erwartet, f"par1={wert}: {modus} statt {erwartet} ({grund})"


def test_par1_drei_ist_kuehlen_nicht_entfrosten():
    """Bis v2.3.1 stand in der Zuordnung faelschlich 3 = Entfrosten. Das Portal
    sagt Cooling - ein Geraet im Kuehlbetrieb waere als Abtauen gemeldet und der
    Volumenstrom auf 0 gesetzt worden."""
    assert betriebsart_aus_par1({"par1": 3.0})[0] == "Kuehlen"


def test_par1_fehlend_oder_unbekannt():
    for daten in ({}, {"par1": None}, {"par1": "abc"}, {"par1": 9.0}):
        modus, grund = betriebsart_aus_par1(daten)
        assert modus is None, f"{daten} haette None ergeben muessen"
        assert grund


def test_abtauen_nur_bei_laufendem_kompressor_und_negativer_spreizung():
    assert ist_abtauen({"par20": 60, "par4": 25.0, "par5": 28.0}) is True
    assert ist_abtauen({"par20": 60, "par4": 33.0, "par5": 31.0}) is False
    assert ist_abtauen({"par20": 0,  "par4": 25.0, "par5": 28.0}) is False
    assert ist_abtauen({"par20": 60, "par4": -99.0, "par5": 28.0}) is False


def test_gemessener_betriebspunkt_vom_22_09_2026():
    """Realer Abruf: par1=2 bei laufendem Kompressor, Vorlauf über Rücklauf."""
    daten = {"par1": 2.0, "par20": 55.0, "par4": 34.1, "par5": 31.4, "par6": 31.6}
    assert betriebsart_aus_par1(daten)[0] == "Heizen"
    assert ist_abtauen(daten) is False


if __name__ == "__main__":
    fns = _alle_tests()
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} Prüfungen bestanden ({len(FAELLE)} Ableitungsfälle darin).")
