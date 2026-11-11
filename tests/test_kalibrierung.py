"""Tests für die Volumenstrom-Kalibrierung aus Warmwasser-Ladungen (v4.2.0).

Ohne Home-Assistant-Abhängigkeit, siehe Kopf von tests/test_mode.py.
"""
import importlib.util
import pathlib
import sys
import types

_ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "es_heatpump"
_PKG = "es_heatpump_unter_test_kalibrierung"
_paket = types.ModuleType(_PKG)
_paket.__path__ = [str(_ROOT)]
sys.modules[_PKG] = _paket


def _lade(name):
    spec = importlib.util.spec_from_file_location(f"{_PKG}.{name}", _ROOT / f"{name}.py")
    modul = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modul
    spec.loader.exec_module(modul)
    return modul


K = _lade("kalibrierung")
C = _lade("const")
LadungsKalibrierung = K.LadungsKalibrierung

TAKT = 10.0  # s, wie der Portalabruf


def _punkt(tw, vor=50.0, rue=45.0, hz=60):
    return {"par7": tw, "par4": vor, "par5": rue, "par20": hz}


def _ladung(kal, t0, *, dauer_min=30, anstieg=10.0, spreizung=5.0, tw0=40.0,
            luecke_bei=None, nachlauf=True, betriebsart="Brauchwasser"):
    """Spielt eine Ladung mit linearem Tw-Anstieg ab; liefert die Endzeit."""
    schritte = int(dauer_min * 60 / TAKT)
    t = t0
    for i in range(schritte + 1):
        if luecke_bei is not None and i == luecke_bei:
            t += 300  # 5 min ohne Werte
        tw = tw0 + anstieg * i / schritte
        kal.messpunkt(t, betriebsart, _punkt(tw, 50.0, 50.0 - spreizung))
        t += TAKT
    if nachlauf:
        for _ in range(int(K.NACHLAUF_S / TAKT) + 1):
            kal.messpunkt(t, "Heizen", _punkt(tw0 + anstieg, 35.0, 32.0))
            t += TAKT
    return t


def _erwartet(speicher_l, anstieg, spreizung, dauer_min):
    return speicher_l / 1000 * anstieg / (spreizung * dauer_min / 60)


def test_eine_ladung_ergibt_den_volumenstrom():
    kal = LadungsKalibrierung(200)
    _ladung(kal, 0, dauer_min=30, anstieg=10.0, spreizung=5.0)
    assert len(kal.ladungen) == 1
    # 0,2 m³ × 10 K / (5 K × 0,5 h) = 0,8 m³/h
    assert abs(kal.ladungen[0]["m3h"] - _erwartet(200, 10, 5, 30)) < 0.01


def test_wert_erst_ab_drei_ladungen_und_median():
    kal = LadungsKalibrierung(200)
    t = 0
    for spreizung in (5.0, 4.0):
        t = _ladung(kal, t, spreizung=spreizung) + 3600
    assert kal.wert() is None
    t = _ladung(kal, t, spreizung=2.0) + 3600
    werte = sorted(_erwartet(200, 10, s, 30) for s in (5.0, 4.0, 2.0))
    assert abs(kal.wert() - werte[1]) < 0.01


def test_nur_die_letzten_ladungen_zaehlen():
    kal = LadungsKalibrierung(200)
    t = 0
    for _ in range(K.ANZAHL_LADUNGEN + 4):
        t = _ladung(kal, t) + 3600
    assert len(kal.ladungen) == K.ANZAHL_LADUNGEN


def test_datenluecke_verwirft_die_ladung():
    kal = LadungsKalibrierung(200)
    _ladung(kal, 0, luecke_bei=50)
    assert kal.ladungen == []
    assert "Datenluecke" in kal.letzte_verworfen


def test_kurze_nachladung_wird_verworfen():
    kal = LadungsKalibrierung(200)
    _ladung(kal, 0, dauer_min=20, anstieg=3.0)
    assert kal.ladungen == []
    assert "waermer" in kal.letzte_verworfen


def test_zu_kurze_ladung_wird_verworfen():
    kal = LadungsKalibrierung(200)
    _ladung(kal, 0, dauer_min=5, anstieg=8.0)
    assert kal.ladungen == []
    assert "kurz" in kal.letzte_verworfen


def test_zapfen_waehrend_der_ladung_verwirft():
    kal = LadungsKalibrierung(200)
    t = 0
    # Anstieg laeuft (40 → 46), dann gezapft (44,5), dann weiter geladen
    verlauf = [40.0 + 0.1 * i for i in range(61)] + [44.5] * 30 + [52.0] * 120
    for tw in verlauf:
        kal.messpunkt(t, "Brauchwasser", _punkt(tw))
        t += TAKT
    for _ in range(int(K.NACHLAUF_S / TAKT) + 1):
        kal.messpunkt(t, "Heizen", _punkt(52.0))
        t += TAKT
    assert kal.ladungen == []
    assert "gezapft" in kal.letzte_verworfen


def test_abtauen_verwirft_die_ladung():
    kal = LadungsKalibrierung(200)
    t = _ladung(kal, 0, nachlauf=False)
    kal.messpunkt(t, "Entfrosten", _punkt(50.0, 30.0, 35.0))
    assert kal.ladungen == []
    assert "Abtauen" in kal.letzte_verworfen


def test_tw_nachlauf_wird_beruecksichtigt():
    """Tw steigt nach dem Umschalten noch - das Maximum im Nachlauf zaehlt."""
    kal = LadungsKalibrierung(200)
    t = _ladung(kal, 0, anstieg=10.0, nachlauf=False)
    kal.messpunkt(t, "Heizen", _punkt(51.0, 35, 32))   # +1 K nach dem Ende
    t += K.NACHLAUF_S
    kal.messpunkt(t, "Heizen", _punkt(50.5, 35, 32))
    assert kal.ladungen[0]["anstieg_k"] == 11.0


def test_heizen_und_heizstab_ohne_verdichter_starten_keine_ladung():
    kal = LadungsKalibrierung(200)
    for i in range(400):
        kal.messpunkt(i * TAKT, "Heizen", _punkt(40 + i * 0.05))
        kal.messpunkt(i * TAKT + 1, "Brauchwasser", _punkt(40 + i * 0.05, hz=0))
    assert not kal.laeuft and kal.ladungen == []


def test_ohne_speichervolumen_inaktiv():
    kal = LadungsKalibrierung(0)
    _ladung(kal, 0)
    assert not kal.aktiv and kal.ladungen == [] and kal.wert() is None


def test_sentinel_temperatur_startet_keine_ladung():
    kal = LadungsKalibrierung(200)
    kal.messpunkt(0, "Brauchwasser", _punkt(-99.0))
    assert not kal.laeuft


def test_uebernehme_rechnet_mit_aktuellem_speichervolumen():
    alt = LadungsKalibrierung(300)
    t = 0
    for _ in range(3):
        t = _ladung(alt, t) + 3600
    neu = LadungsKalibrierung(200)
    neu.uebernehme(alt.ladungen + [{"kaputt": 1}, "quatsch"])
    assert len(neu.ladungen) == 3
    assert abs(neu.wert() - alt.wert() * 200 / 300) < 0.01


def test_wirksame_volumenstroeme():
    w = K.wirksame_volumenstroeme
    assert w("aus", 2.0, 1.8, 1.4) == (2.0, 1.8)
    assert w("warmwasser", 2.0, 1.8, 1.4) == (2.0, 1.4)
    assert w("beide", 2.0, 1.8, 1.4) == (1.4, 1.4)
    assert w("beide", 2.0, 1.8, None) == (2.0, 1.8)
    assert w("unsinn", 2.0, 1.8, 1.4) == (2.0, 1.8)


def test_optionen_passen_zu_den_konstanten():
    assert C.DEFAULT_FLOW_CALIBRATION in K.KALIBRIERUNG_OPTIONEN
    assert C.DEFAULT_FLOW_CALIBRATION == K.KALIBRIERUNG_AUS


def test_abfall_vor_dem_anstieg_ist_kein_zapfen():
    """Geduscht beim Start (gemessen 04.11.2026: 45,3 → 38,9 °C), dann Ladung.

    Startwert ist das Minimum vor dem Anstieg; der Wert beim Umschalten darf
    weder als Startwert noch als Maximum fuer die Zapf-Erkennung dienen
    (Fehler im ersten Entwurf: 10.11. 06:05 als "gezapft" verworfen).
    """
    kal = LadungsKalibrierung(200)
    t = 0
    verlauf = [44.1 - 0.1 * i for i in range(16)] + [42.5 + 0.075 * i for i in range(201)]
    for tw in verlauf:
        kal.messpunkt(t, "Brauchwasser", _punkt(tw, 50.0, 47.5))
        t += TAKT
    for _ in range(int(K.NACHLAUF_S / TAKT) + 1):
        kal.messpunkt(t, "Heizen", _punkt(verlauf[-1], 35.0, 32.0))
        t += TAKT
    assert kal.letzte_verworfen is None
    assert len(kal.ladungen) == 1
    assert abs(kal.ladungen[0]["anstieg_k"] - (verlauf[-1] - 42.5)) < 0.01
