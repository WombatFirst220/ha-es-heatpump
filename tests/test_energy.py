"""Tests fuer die Energiezaehler der Auswertungsseite und den Aenderungsverlauf.

Bewusst ohne Home Assistant: ``energy.py`` importiert nur aus ``const`` und
``flow``, ``backup.py`` nur aus ``settings`` - alles reines Python.

Aufruf:  python3 -m pytest tests/ -q
"""
import importlib.util
import pathlib
import sys
import types

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "es_heatpump"
_PKG = "es_heatpump_unter_test_energie"
_paket = types.ModuleType(_PKG)
_paket.__path__ = [str(_ROOT)]
sys.modules[_PKG] = _paket


def _lade(name):
    voll = f"{_PKG}.{name}"
    if voll in sys.modules:
        return sys.modules[voll]
    spec = importlib.util.spec_from_file_location(voll, _ROOT / f"{name}.py")
    modul = importlib.util.module_from_spec(spec)
    sys.modules[voll] = modul
    spec.loader.exec_module(modul)
    return modul


_lade("const")
_lade("flow")
E = _lade("energy")
S = _lade("settings")
B = _lade("backup")

H = 3600.0


# ── Hilfsfunktionen ──────────────────────────────────────────────────────

@pytest.mark.parametrize("modus, teil", [
    ("Heizen", E.HEIZEN),
    ("Entfrosten", E.HEIZEN),
    ("Brauchwasser", E.WARMWASSER),
    ("Brauchwasser + Heizen", E.WARMWASSER),
    ("Brauchwasser + Kuehlen", E.WARMWASSER),
    ("Aus", None),
    ("Kuehlen", None),
    ("Unbekannt", None),
    (None, None),
])
def test_kategorie(modus, teil):
    assert E.kategorie_von(modus) == teil


@pytest.mark.parametrize("roh, einheit, erwartet", [
    ("1500", "W", 1500.0),
    ("-1500", "W", 1500.0),        # Bezug negativ gemeldet
    ("1.5", "kW", 1500.0),
    ("200", None, 200.0),
    ("unknown", "W", None),
    ("unavailable", "W", None),
    ("", "W", None),
    ("abc", "W", None),
    ("nan", "W", None),
    ("inf", "W", None),
])
def test_leistung_in_w(roh, einheit, erwartet):
    assert E.leistung_in_w(roh, einheit) == erwartet


def test_thermische_leistung():
    d = {"par4": 35.0, "par5": 30.0, "par20": 50}
    assert E.thermische_leistung_w(d, "Heizen", 2.0, 1.0) == pytest.approx(2.0 * 5 * 1163)
    assert E.thermische_leistung_w(d, "Brauchwasser", 2.0, 1.0) == pytest.approx(5 * 1163)
    # Live-Volumenstrom gewinnt
    assert E.thermische_leistung_w(d, "Heizen", 2.0, 1.0, 1.5) == pytest.approx(1.5 * 5 * 1163)
    # Kein Waermeeintrag
    assert E.thermische_leistung_w(d, "Entfrosten", 2.0, 1.0) == 0.0
    assert E.thermische_leistung_w(d, "Aus", 2.0, 1.0) == 0.0
    assert E.thermische_leistung_w({**d, "par20": 0}, "Heizen", 2.0, 1.0) == 0.0
    assert E.thermische_leistung_w({**d, "par20": None}, "Heizen", 2.0, 1.0) == 0.0
    assert E.thermische_leistung_w({**d, "par5": 36.0}, "Heizen", 2.0, 1.0) == 0.0
    # Fehlende Temperaturen
    assert E.thermische_leistung_w({"par4": 35.0}, "Heizen", 2.0, 1.0) is None
    assert E.thermische_leistung_w(None, "Heizen", 2.0, 1.0) is None


# ── EnergieZaehler ───────────────────────────────────────────────────────

def test_links_rechteck_mit_wert_zu_beginn():
    z = E.EnergieZaehler(15 * 60, E.METHODE_LINKS)
    assert z.messpunkt(0, 1000, E.HEIZEN) == 0.0
    # 1000 W fuer 10 min = 1/6 kWh, gebucht auf Heizen
    assert z.messpunkt(600, 3000, E.WARMWASSER) == pytest.approx(1000 * 600 / 3.6e6)
    # 3000 W fuer 5 min, gebucht auf Warmwasser (Betriebsart zu Beginn)
    z.messpunkt(900, 0, None)
    assert z.summen[E.HEIZEN] == pytest.approx(1000 * 600 / 3.6e6)
    assert z.summen[E.WARMWASSER] == pytest.approx(3000 * 300 / 3.6e6)
    assert z.summen[E.GESAMT] == pytest.approx(z.summen[E.HEIZEN] + z.summen[E.WARMWASSER])


def test_trapez():
    z = E.EnergieZaehler(10 * 60, E.METHODE_TRAPEZ)
    z.messpunkt(0, 0, E.HEIZEN)
    z.messpunkt(60, 6000, E.HEIZEN)
    assert z.summen[E.GESAMT] == pytest.approx(3000 * 60 / 3.6e6)
    assert z.summen[E.HEIZEN] == z.summen[E.GESAMT]


def test_rest_nur_in_gesamtsumme():
    z = E.EnergieZaehler(15 * 60)
    z.messpunkt(0, 3600, None)
    z.messpunkt(H / 6, 0, None)   # 10 min
    assert z.summen[E.GESAMT] == pytest.approx(0.6)
    assert z.summen[E.HEIZEN] == 0.0
    assert z.summen[E.WARMWASSER] == 0.0


def test_luecke_wird_verworfen():
    z = E.EnergieZaehler(15 * 60)
    z.messpunkt(0, 2000, E.HEIZEN)
    assert z.messpunkt(16 * 60, 2000, E.HEIZEN) == 0.0
    assert z.summen[E.GESAMT] == 0.0
    # Danach geht es normal weiter
    z.messpunkt(16 * 60 + 360, 2000, E.HEIZEN)
    assert z.summen[E.GESAMT] == pytest.approx(2000 * 360 / 3.6e6)


def test_unavailable_beendet_kette():
    links = E.EnergieZaehler(15 * 60, E.METHODE_LINKS)
    links.messpunkt(0, 1200, E.HEIZEN)
    # Bis zum Ausfall galt der alte Wert noch
    assert links.messpunkt(300, None) == pytest.approx(1200 * 300 / 3.6e6)
    # Nach dem Ausfall: neuer Anfang, nichts nachgebucht
    assert links.messpunkt(600, 1200, E.HEIZEN) == 0.0
    assert links.summen[E.GESAMT] == pytest.approx(1200 * 300 / 3.6e6)

    trapez = E.EnergieZaehler(10 * 60, E.METHODE_TRAPEZ)
    trapez.messpunkt(0, 1200, E.HEIZEN)
    assert trapez.messpunkt(300, None) == 0.0
    assert trapez.messpunkt(400, 1200, E.HEIZEN) == 0.0
    assert trapez.summen[E.GESAMT] == 0.0


def test_zeit_rueckwaerts_bucht_nichts():
    z = E.EnergieZaehler(15 * 60)
    z.messpunkt(100, 1000, E.HEIZEN)
    assert z.messpunkt(50, 1000, E.HEIZEN) == 0.0
    assert z.summen[E.GESAMT] == 0.0


def test_negative_leistung_zaehlt_nicht_rueckwaerts():
    z = E.EnergieZaehler(15 * 60)
    z.messpunkt(0, -500, E.HEIZEN)
    z.messpunkt(60, 0, E.HEIZEN)
    assert z.summen[E.GESAMT] == 0.0


def test_uebernehme_addiert_und_ignoriert_unsinn():
    z = E.EnergieZaehler(15 * 60)
    z.messpunkt(0, 3600, E.HEIZEN)
    z.messpunkt(H / 6, 0, E.HEIZEN)
    z.uebernehme(E.GESAMT, 100.0)
    z.uebernehme(E.HEIZEN, "40.5")
    z.uebernehme(E.WARMWASSER, "kaputt")
    z.uebernehme(E.WARMWASSER, -3)
    assert z.summen[E.GESAMT] == pytest.approx(100.6)
    assert z.summen[E.HEIZEN] == pytest.approx(41.1)
    assert z.summen[E.WARMWASSER] == 0.0
    with pytest.raises(KeyError):
        z.uebernehme("kuehlen", 1)


def test_unbekannte_methode():
    with pytest.raises(ValueError):
        E.EnergieZaehler(60, "simpson")


def test_slugs_der_zaehler():
    slugs = [s for s, _, _ in E.ENERGIE_ZAEHLER]
    assert slugs == [
        "energie_elektrisch", "energie_elektrisch_heizen", "energie_elektrisch_warmwasser",
        "energie_thermisch", "energie_thermisch_heizen", "energie_thermisch_warmwasser",
    ]


# ── VerdichterZaehler ────────────────────────────────────────────────────

def test_verdichter_starts_und_laufzeit():
    v = E.VerdichterZaehler(10 * 60)
    v.messpunkt(0, 0)
    assert v.messpunkt(60, 45) is True          # Start
    assert v.starts == 1
    v.messpunkt(120, 50)                        # laeuft weiter, kein Start
    v.messpunkt(180, 0)                         # stoppt
    assert v.starts == 1
    assert v.laufzeit_h == pytest.approx(120 / H)
    v.messpunkt(240, 30)
    assert v.starts == 2


def test_verdichter_erster_messpunkt_ist_kein_start():
    v = E.VerdichterZaehler()
    v.messpunkt(0, 50)
    assert v.starts == 0
    v.messpunkt(60, 50)
    assert v.laufzeit_h == pytest.approx(60 / H)


def test_verdichter_fehlender_wert_zaehlt_keinen_start():
    v = E.VerdichterZaehler()
    v.messpunkt(0, 0)
    v.messpunkt(60, 40)
    v.messpunkt(120, None)
    v.messpunkt(180, 40)
    assert v.starts == 1
    assert v.laufzeit_h == pytest.approx(120 / H)   # 60..180 s gelaufen


def test_verdichter_luecke():
    v = E.VerdichterZaehler(10 * 60)
    v.messpunkt(0, 40)
    v.messpunkt(11 * 60, 40)
    assert v.laufzeit_h == 0.0
    v.messpunkt(12 * 60, 0)
    v.messpunkt(30 * 60, 40)    # Start ueber eine Luecke hinweg zaehlt trotzdem
    assert v.starts == 1


def test_verdichter_uebernehme():
    v = E.VerdichterZaehler()
    v.uebernehme(starts="12", laufzeit_h=3.5)
    v.uebernehme(starts="x", laufzeit_h=None)
    assert v.starts == 12
    assert v.laufzeit_h == pytest.approx(3.5)


# ── Aenderungsverlauf aus den Sicherungen ────────────────────────────────

def _bekannte_schreibbare(n):
    return [p for p, s in S.SETTINGS.items() if s.writable][:n]


def _sicherung(kennung, zeit, pars, anlass=B.ANLASS_AUTOMATISCH):
    return B.Sicherung(id=kennung, zeitpunkt=zeit, anlass=anlass, pars=dict(pars))


def test_aenderungsverlauf():
    p1, p2 = _bekannte_schreibbare(2)
    basis = {p1: 1, p2: 0, "par999": 5}
    s1 = _sicherung("a", "2026-01-01T10:00:00+01:00", basis, B.ANLASS_ERSTE)
    s2 = _sicherung("b", "2026-01-02T10:00:00+01:00", {**basis, "par999": 6})    # nur unbenannt
    s3 = _sicherung("c", "2026-01-03T10:00:00+01:00", {**basis, p2: 1, "par999": 6},
                    B.ANLASS_VOR_SCHREIBEN)
    s4 = _sicherung("d", "2026-01-04T10:00:00+01:00", {**basis, p2: 1, "par999": 6})  # gleich
    # Reihenfolge der Eingabe egal (Ablage liefert neueste zuerst)
    verlauf = B.aenderungsverlauf([s4, s2, s3, s1])
    assert len(verlauf) == 1
    eintrag = verlauf[0]
    assert eintrag["time"] == "2026-01-03T09:00:00+00:00"
    assert eintrag["reason"] == B.ANLASS_VOR_SCHREIBEN
    assert len(eintrag["items"]) == 1
    posten = eintrag["items"][0]
    assert posten["par"] == p2
    assert posten["old"] == 0 and posten["new"] == 1
    assert posten["name"] == S.SETTINGS[p2].name
    assert posten["group"] == S.SETTINGS[p2].group
    assert S.SETTINGS[p2].name in posten["text"] and "→" in posten["text"]


def test_aenderungsverlauf_mit_unbenannten_feldern():
    s1 = _sicherung("a", "2026-01-01T10:00:00+00:00", {"par999": 5})
    s2 = _sicherung("b", "2026-01-02T10:00:00+00:00", {"par999": 6})
    assert B.aenderungsverlauf([s1, s2]) == []
    verlauf = B.aenderungsverlauf([s1, s2], nur_bekannte=False)
    assert verlauf[0]["items"][0]["group"] == "Ohne Katalogeintrag"


def test_aenderungsverlauf_leer_und_einzeln():
    assert B.aenderungsverlauf([]) == []
    assert B.aenderungsverlauf([_sicherung("a", "2026-01-01T10:00:00+00:00", {"par1": 1})]) == []


def test_aenderungsverlauf_feld_entfernt():
    p1 = _bekannte_schreibbare(1)[0]
    s1 = _sicherung("a", "2026-01-01T10:00:00", {p1: 1})          # ohne Zone -> UTC
    s2 = _sicherung("b", "2026-01-02T10:00:00", {})
    verlauf = B.aenderungsverlauf([s1, s2])
    assert verlauf[0]["time"] == "2026-01-02T10:00:00+00:00"
    assert verlauf[0]["items"][0]["new"] is None
    assert verlauf[0]["items"][0]["text"].endswith("→ -")
